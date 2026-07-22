from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver

class Speciality(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Specialities"

    def __str__(self):
        return self.name

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    speciality = models.ForeignKey(Speciality, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    can_add_patient = models.BooleanField(default=True)
    can_serve_patient = models.BooleanField(default=True)
    can_manage_settings = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} ({self.speciality.name if self.speciality else 'No Speciality'})"

# Ensure UserProfile is automatically created when a User is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    try:
        instance.profile.save()
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(user=instance)

class Room(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    start_token = models.PositiveIntegerField(default=1, help_text="First token number for this room each day. Tokens continue from here or from the last issued number.")

    def __str__(self):
        return self.name

class RoomGroup(models.Model):
    """A named group of rooms (e.g. 'Consultation', 'OPD', 'Emergency Ward')."""
    name = models.CharField(max_length=100, unique=True)
    rooms = models.ManyToManyField(Room, related_name='groups', blank=True)

    def __str__(self):
        return self.name

class PatientCondition(models.Model):
    name = models.CharField(max_length=50, unique=True)
    # Tailwind color scheme name (e.g., 'rose', 'emerald', 'amber', 'blue', 'gray')
    color_theme = models.CharField(max_length=20, default='blue', help_text="Tailwind color scheme name (emerald, rose, amber, blue, gray)")

    def __str__(self):
        return self.name

class Patient(models.Model):
    STATUS_CHOICES = [
        ('WAITING', 'Waiting'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled/Skipped'),
        ('TRANSFERRED', 'Transferred'),
    ]

    pid = models.CharField(max_length=50, help_text="Patient ID")
    name = models.CharField(max_length=100)
    token = models.PositiveIntegerField(blank=True)
    condition = models.ForeignKey(PatientCondition, on_delete=models.PROTECT, related_name='patients')
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='patients')
    note = models.TextField(blank=True, null=True, help_text="Additional doctor notes or patient complaints")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='WAITING')
    referred_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        # Auto-generate token if not set
        if not self.token:
            today = timezone.localdate()
            # Get the max token for patients registered today for this specific room
            max_token = Patient.objects.filter(
                created_at__date=today,
                room=self.room
            ).aggregate(models.Max('token'))['token__max']
            if max_token is not None:
                # Continue from last issued token
                self.token = max_token + 1
            else:
                # No patients yet today — start from room's configured start_token
                self.token = self.room.start_token
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Token {self.token}: {self.name} (PID: {self.pid}) in {self.room.name}"

from django.db.models.signals import post_delete
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

@receiver(post_save, sender=Patient)
def broadcast_patient_save(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    if channel_layer:
        try:
            async_to_sync(channel_layer.group_send)(
                'queue_group',
                {
                    'type': 'queue_update',
                    'action': 'create' if created else 'update',
                    'patient': {
                        'id': instance.id,
                        'pid': instance.pid,
                        'name': instance.name,
                        'token': instance.token,
                        'condition': instance.condition.name,
                        'condition_id': instance.condition.id,
                        'condition_color': instance.condition.color_theme,
                        'room_id': instance.room.id,
                        'room_no': instance.room.name,
                        'note': instance.note or '',
                        'status': instance.status,
                        'status_display': instance.get_status_display(),
                        'updated_at': instance.updated_at.isoformat()
                    }
                }
            )
        except Exception as e:
            pass

@receiver(post_delete, sender=Patient)
def broadcast_patient_delete(sender, instance, **kwargs):
    channel_layer = get_channel_layer()
    if channel_layer:
        try:
            async_to_sync(channel_layer.group_send)(
                'queue_group',
                {
                    'type': 'queue_update',
                    'action': 'delete',
                    'patient': {
                        'id': instance.id
                    }
                }
            )
        except Exception as e:
            pass





class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    rooms = models.ManyToManyField(Room, related_name='departments', blank=True)

    def __str__(self):
        return self.name






class RegisterIssue(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]


    room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='register_issues'
    )
    reported_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reported_register_issues'
    )
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='register_issues'
    )   

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.status})"
