from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import models
from django.contrib.auth.models import User
import json
from .models import Speciality, UserProfile, PatientCondition, Room, Patient, RoomGroup
from django.http import JsonResponse

def check_and_seed_db():
    """Seeds the database with basic specialities, conditions, and rooms if they are empty."""
    if Speciality.objects.count() == 0:
        Speciality.objects.create(name="Administrator", description="System administrator")
        Speciality.objects.create(name="Receptionist", description="Registers and manages incoming patients")
        Speciality.objects.create(name="Ophthalmologist", description="Eye doctor / specialist")
        Speciality.objects.create(name="Optometrist", description="Refraction and vision screening specialist")
        
    if PatientCondition.objects.count() == 0:
        PatientCondition.objects.create(name="Normal", color_theme="blue")
        PatientCondition.objects.create(name="Emergency", color_theme="rose")
        PatientCondition.objects.create(name="Urgent", color_theme="amber")

    if Room.objects.count() == 0:
        Room.objects.create(name="Room 1", description="General Eye Exam")
        Room.objects.create(name="Room 2", description="Refraction & Glasses")
        Room.objects.create(name="Room 3", description="Specialist Diagnostics")

def login_view(request):
    check_and_seed_db()
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect('login')

@login_required
def dashboard_view(request):
    check_and_seed_db()
    today = timezone.localdate()

    # --- Date filter (for history log) ---
    date_from_str = request.GET.get('date_from', '').strip()
    date_to_str   = request.GET.get('date_to', '').strip()

    from datetime import date as dt_date
    def parse_date(s):
        try:
            return dt_date.fromisoformat(s)
        except (ValueError, AttributeError):
            return None

    date_from = parse_date(date_from_str)
    date_to   = parse_date(date_to_str)

    # Active patients always show today only (real-time queue)
    active_patients = Patient.objects.filter(
        status__in=['WAITING', 'IN_PROGRESS'],
        created_at__date=today
    ).select_related('room', 'condition').order_by('created_at')

    # History: apply date filter if provided, else default to today
    history_qs = Patient.objects.filter(
        status__in=['COMPLETED', 'CANCELLED', 'TRANSFERRED'],
    ).select_related('room').order_by('-updated_at')

    if date_from and date_to:
        history_qs = history_qs.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    elif date_from:
        history_qs = history_qs.filter(created_at__date__gte=date_from)
    elif date_to:
        history_qs = history_qs.filter(created_at__date__lte=date_to)
    else:
        history_qs = history_qs.filter(created_at__date=today)

    history_patients = history_qs

    # Metrics (always today)
    total_waiting = Patient.objects.filter(status='WAITING', created_at__date=today).count()
    currently_serving = Patient.objects.filter(status='IN_PROGRESS', created_at__date=today).count()
    completed_today = Patient.objects.filter(status='COMPLETED', created_at__date=today).count()
    emergencies_waiting = Patient.objects.filter(
        status='WAITING',
        condition__name='Emergency',
        created_at__date=today
    ).count()

    rooms = Room.objects.all()

    # Pass filter values back so the template can pre-fill the inputs
    context = {
        'active_patients': active_patients,
        'history_patients': history_patients,
        'total_waiting': total_waiting,
        'currently_serving': currently_serving,
        'completed_today': completed_today,
        'emergencies_waiting': emergencies_waiting,
        'rooms': rooms,
        'date_from': date_from_str,
        'date_to': date_to_str,
        'today_str': str(today),
    }
    return render(request, 'dashboard.html', context)

@login_required
def add_patient_view(request):
    check_and_seed_db()
    
    # Check permissions
    if not request.user.is_superuser and not request.user.profile.can_add_patient:
        messages.error(request, "You do not have permission to register patients.")
        return redirect('dashboard')

    conditions = PatientCondition.objects.all()
    rooms = Room.objects.all()
    
    # Calculate next token preview for each room and format as JSON for templates
    today = timezone.localdate()
    room_next_tokens = {}
    for r in rooms:
        max_token = Patient.objects.filter(created_at__date=today, room=r).aggregate(models.Max('token'))['token__max']
        room_next_tokens[r.id] = (max_token or 0) + 1

    if request.method == 'POST':
        pid = request.POST.get('pid', '').strip()
        name = request.POST.get('name', '').strip()
        condition_id = request.POST.get('condition')
        room_id = request.POST.get('room')
        note = request.POST.get('note', '')

        if not pid or not name or not condition_id or not room_id:
            messages.error(request, "Please fill in all required fields.")
        elif Patient.objects.filter(pid__iexact=pid, status__in=['WAITING', 'IN_PROGRESS']).exists():
            messages.error(request, f"Patient with PID '{pid}' is already active in the queue.")
        else:
            try:
                condition = PatientCondition.objects.get(id=condition_id)
                room = Room.objects.get(id=room_id)
                patient = Patient.objects.create(
                    pid=pid,
                    name=name,
                    condition=condition,
                    room=room,
                    note=note,
                    status='WAITING'
                )
                messages.success(request, f"Patient {patient.name} registered with Token #{patient.token} in {room.name}!")
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f"Error saving patient: {str(e)}")

    room_groups = RoomGroup.objects.prefetch_related('rooms').all()

    context = {
        'conditions': conditions,
        'rooms': rooms,
        'room_groups': room_groups,
        'room_next_tokens_json': json.dumps(room_next_tokens),
    }
    return render(request, 'add_patient.html', context)

@login_required
def edit_patient_view(request, pk):
    check_and_seed_db()
    
    # Check permissions
    if not request.user.is_superuser and not request.user.profile.can_serve_patient:
        messages.error(request, "You do not have permission to manage patients.")
        return redirect('dashboard')

    patient = get_object_or_404(Patient, pk=pk)
    conditions = PatientCondition.objects.all()
    rooms = Room.objects.all()

    # Fetch previous visits/history for this patient (same PID)
    previous_visits = Patient.objects.filter(pid__iexact=patient.pid).exclude(id=patient.id).select_related('room', 'condition').order_by('-created_at')

    if request.method == 'POST':
        pid = request.POST.get('pid', '').strip()
        name = request.POST.get('name', '').strip()
        condition_id = request.POST.get('condition')
        room_id = request.POST.get('room')
        note = request.POST.get('note', '')
        status = request.POST.get('status')

        if not pid or not name or not condition_id or not room_id or not status:
            messages.error(request, "Please fill in all required fields.")
        elif Patient.objects.filter(pid__iexact=pid, status__in=['WAITING', 'IN_PROGRESS']).exclude(id=patient.id).exists():
            messages.error(request, f"Another patient with PID '{pid}' is already active in the queue.")
        else:
            try:
                condition = PatientCondition.objects.get(id=condition_id)
                room = Room.objects.get(id=room_id)
                
                # Check if room is changing. If room changes, re-calculate token for the new room!
                if patient.room != room:
                    patient.room = room
                    # Reset token to force recalculation on save()
                    patient.token = None

                patient.pid = pid
                patient.name = name
                patient.condition = condition
                patient.note = note
                patient.status = status
                patient.save()
                
                messages.success(request, f"Patient {patient.name} (Token #{patient.token} in {room.name}) updated successfully!")
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, f"Error updating patient: {str(e)}")

    context = {
        'patient': patient,
        'conditions': conditions,
        'rooms': rooms,
        'statuses': Patient.STATUS_CHOICES,
        'previous_visits': previous_visits,
    }
    return render(request, 'edit_patient.html', context)

@login_required
def transfer_patient_view(request, pk):
    """Transfers a patient to another room, completing the current queue item and adding a new waiting queue item."""
    if not request.user.is_superuser and not request.user.profile.can_serve_patient:
        messages.error(request, "You do not have permission to transfer patients.")
        return redirect('dashboard')

    patient = get_object_or_404(Patient, pk=pk)

    if request.method == 'POST':
        room_id = request.POST.get('room')
        if not room_id:
            messages.error(request, "Target room is required for transfer.")
            return redirect('edit_patient', pk=pk)

        try:
            target_room = Room.objects.get(id=room_id)
            if patient.room == target_room:
                messages.error(request, "Patient is already assigned to this room.")
                return redirect('edit_patient', pk=pk)

            old_room_name = patient.room.name
            
            # 1. Update current patient status to TRANSFERRED
            patient.status = 'TRANSFERRED'
            patient.save()

            # 2. Create the new patient record in target room
            new_patient = Patient.objects.create(
                pid=patient.pid,
                name=patient.name,
                condition=patient.condition,
                room=target_room,
                note=patient.note, # copy notes/diagnosis
                status='WAITING',
                referred_from=patient # link to previous session
            )

            messages.success(request, f"Patient {patient.name} transferred from {old_room_name} to {target_room.name} with Token #{new_patient.token}!")
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f"Error transferring patient: {str(e)}")
            return redirect('edit_patient', pk=pk)

    return redirect('edit_patient', pk=pk)

@login_required
def delete_patient_view(request, pk):
    # Check permissions
    if not request.user.is_superuser and not request.user.profile.can_serve_patient:
        messages.error(request, "You do not have permission to delete patients.")
        return redirect('dashboard')

    patient = get_object_or_404(Patient, pk=pk)
    name = patient.name
    token = patient.token
    room_name = patient.room.name
    patient.delete()
    messages.success(request, f"Patient {name} (Token #{token} in {room_name}) deleted.")
    return redirect('dashboard')

def track_patient_view(request):
    check_and_seed_db()
    search_query = request.GET.get('query', '').strip()
    patient = None
    patients_list = None
    queue_position = None
    patients_ahead = None
    previous_visits = None

    if search_query:
        # 1. Search by PID (globally unique)
        patient = Patient.objects.filter(
            pid__iexact=search_query,
            status__in=['WAITING', 'IN_PROGRESS']
        ).select_related('room', 'condition').first()
        
        # 2. If not found by PID, check if it's a token search
        if not patient and search_query.isdigit():
            today = timezone.localdate()
            matches = Patient.objects.filter(
                token=int(search_query),
                status__in=['WAITING', 'IN_PROGRESS'],
                created_at__date=today
            ).select_related('room', 'condition')
            
            if matches.count() == 1:
                patient = matches.first()
            elif matches.count() > 1:
                patients_list = matches
            else:
                messages.error(request, f"No active patient found today matching token: '{search_query}'.")
        elif not patient:
            messages.error(request, f"No active patient found matching Patient ID: '{search_query}'.")

        # 3. Position is room-specific: count WAITING patients with a lower
        #    token in the same room today (completed/cancelled don't affect it).
        if patient:
            previous_visits = Patient.objects.filter(pid__iexact=patient.pid).exclude(id=patient.id).select_related('room', 'condition').order_by('-created_at')
            if patient.status == 'WAITING':
                patients_ahead = Patient.objects.filter(
                    status='WAITING',
                    room=patient.room,
                    created_at__date=timezone.localdate(),
                    token__lt=patient.token
                ).count()
                queue_position = patients_ahead + 1

    context = {
        'patient': patient,
        'patients_list': patients_list,
        'queue_position': queue_position,
        'patients_ahead': patients_ahead,
        'previous_visits': previous_visits,
        'query': search_query,
    }
    return render(request, 'track_patient.html', context)

def calling_board_view(request):
    check_and_seed_db()
    today = timezone.localdate()
    # Fetch rooms and the active patients (IN_PROGRESS) currently in each room (up to 3)
    rooms = Room.objects.all().order_by('name')
    active_calls = {}
    for room in rooms:
        active_patients = Patient.objects.filter(
            room=room,
            status='IN_PROGRESS',
            created_at__date=today
        ).order_by('-updated_at')[:3]
        active_calls[room.id] = list(active_patients)

    context = {
        'rooms': rooms,
        'active_calls': active_calls,
    }
    return render(request, 'calling_board.html', context)

@login_required
def settings_view(request):
    check_and_seed_db()
    
    # Check if user has permission to manage settings
    if not request.user.is_superuser and not request.user.profile.can_manage_settings:
        messages.error(request, "Access denied. Administrator privileges required.")
        return redirect('dashboard')

    conditions = PatientCondition.objects.all()
    specialities = Speciality.objects.all()
    rooms = Room.objects.all()
    staff_members = UserProfile.objects.all().select_related('user', 'speciality')

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_condition':
            name = request.POST.get('name', '').strip()
            color_theme = request.POST.get('color_theme', 'blue')
            if name:
                if PatientCondition.objects.filter(name__iexact=name).exists():
                    messages.error(request, f"Condition '{name}' already exists.")
                else:
                    PatientCondition.objects.create(name=name, color_theme=color_theme)
                    messages.success(request, f"Condition '{name}' added successfully.")
            else:
                messages.error(request, "Condition name cannot be empty.")
                
        elif action == 'add_room':
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            if name:
                if Room.objects.filter(name__iexact=name).exists():
                    messages.error(request, f"Room '{name}' already exists.")
                else:
                    Room.objects.create(name=name, description=description)
                    messages.success(request, f"Room '{name}' added successfully.")
            else:
                messages.error(request, "Room name cannot be empty.")

        elif action == 'set_start_token':
            room_id = request.POST.get('room_id')
            start_token = request.POST.get('start_token', '').strip()
            if room_id and start_token.isdigit() and int(start_token) >= 1:
                try:
                    room = Room.objects.get(id=room_id)
                    room.start_token = int(start_token)
                    room.save()
                    messages.success(request, f"Start token for {room.name} set to #{start_token}.")
                except Room.DoesNotExist:
                    messages.error(request, "Room not found.")
            else:
                messages.error(request, "Please enter a valid token number (≥ 1).")

        elif action == 'add_speciality':
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            if name:
                if Speciality.objects.filter(name__iexact=name).exists():
                    messages.error(request, f"Role/Speciality '{name}' already exists.")
                else:
                    Speciality.objects.create(name=name, description=description)
                    messages.success(request, f"Role/Speciality '{name}' added successfully.")
            else:
                messages.error(request, "Role name cannot be empty.")

        elif action == 'add_staff':
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '')
            speciality_id = request.POST.get('speciality')
            
            # Read permissions
            can_add_patient = request.POST.get('can_add_patient') == 'on'
            can_serve_patient = request.POST.get('can_serve_patient') == 'on'
            can_manage_settings = request.POST.get('can_manage_settings') == 'on'
            
            if username and password and speciality_id:
                if User.objects.filter(username=username).exists():
                    messages.error(request, f"Username '{username}' already exists.")
                else:
                    try:
                        speciality = Speciality.objects.get(id=speciality_id)
                        new_user = User.objects.create_user(username=username, email=email, password=password)
                        
                        # Apply permissions
                        new_user.profile.speciality = speciality
                        new_user.profile.can_add_patient = can_add_patient
                        new_user.profile.can_serve_patient = can_serve_patient
                        new_user.profile.can_manage_settings = can_manage_settings
                        new_user.profile.save()
                        
                        messages.success(request, f"Staff member '{username}' registered successfully.")
                    except Exception as e:
                        messages.error(request, f"Error registering staff: {str(e)}")
            else:
                messages.error(request, "Username, password, and speciality are required.")
                
        elif action == 'add_room_group':
            group_name = request.POST.get('group_name', '').strip()
            room_ids = request.POST.getlist('group_rooms')
            if group_name:
                if RoomGroup.objects.filter(name__iexact=group_name).exists():
                    messages.error(request, f"Group '{group_name}' already exists.")
                else:
                    grp = RoomGroup.objects.create(name=group_name)
                    if room_ids:
                        grp.rooms.set(Room.objects.filter(id__in=room_ids))
                    messages.success(request, f"Group '{group_name}' created successfully.")
            else:
                messages.error(request, "Group name cannot be empty.")

        elif action == 'delete_room_group':
            group_id = request.POST.get('group_id')
            try:
                grp = RoomGroup.objects.get(id=group_id)
                grp_name = grp.name
                grp.delete()
                messages.success(request, f"Group '{grp_name}' deleted.")
            except RoomGroup.DoesNotExist:
                messages.error(request, "Group not found.")

        elif action == 'edit_room_group':
            group_id = request.POST.get('group_id')
            group_name = request.POST.get('group_name', '').strip()
            room_ids = request.POST.getlist('group_rooms')
            try:
                grp = RoomGroup.objects.get(id=group_id)
                if group_name:
                    # Check name uniqueness (ignore self)
                    if RoomGroup.objects.filter(name__iexact=group_name).exclude(id=group_id).exists():
                        messages.error(request, f"Another group named '{group_name}' already exists.")
                    else:
                        grp.name = group_name
                        grp.save()
                        grp.rooms.set(Room.objects.filter(id__in=room_ids))
                        messages.success(request, f"Group '{group_name}' updated successfully.")
                else:
                    messages.error(request, "Group name cannot be empty.")
            except RoomGroup.DoesNotExist:
                messages.error(request, "Group not found.")

        return redirect('settings')

    room_groups = RoomGroup.objects.prefetch_related('rooms').all()

    context = {
        'conditions': conditions,
        'specialities': specialities,
        'rooms': rooms,
        'staff_members': staff_members,
        'room_groups': room_groups,
        'color_themes': ['blue', 'emerald', 'rose', 'amber', 'purple', 'indigo', 'orange', 'sky']
    }
    return render(request, 'settings.html', context)


def get_group_rooms_view(request, group_id):
    """AJAX endpoint: returns rooms in a group + the recommended (least busy) room."""
    try:
        group = RoomGroup.objects.prefetch_related('rooms').get(id=group_id)
    except RoomGroup.DoesNotExist:
        return JsonResponse({'error': 'Group not found'}, status=404)

    today = timezone.localdate()
    rooms_data = []
    best_room_id = None
    min_count = None

    for room in group.rooms.all():
        waiting_count = Patient.objects.filter(
            room=room,
            status__in=['WAITING', 'IN_PROGRESS'],
            created_at__date=today
        ).count()
        # Calculate next token for this room
        max_token = Patient.objects.filter(
            created_at__date=today, room=room
        ).aggregate(models.Max('token'))['token__max']
        next_token = (max_token or room.start_token - 1) + 1

        rooms_data.append({
            'id': room.id,
            'name': room.name,
            'waiting_count': waiting_count,
            'next_token': next_token,
        })

        if min_count is None or waiting_count < min_count:
            min_count = waiting_count
            best_room_id = room.id

    return JsonResponse({
        'rooms': rooms_data,
        'recommended_room_id': best_room_id,
    })



@login_required
def problem_view(request):
    return render(request, 'problems.html')