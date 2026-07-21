from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('patient/add/', views.add_patient_view, name='add_patient'),
    path('patient/edit/<int:pk>/', views.edit_patient_view, name='edit_patient'),
    path('patient/delete/<int:pk>/', views.delete_patient_view, name='delete_patient'),
    path('patient/transfer/<int:pk>/', views.transfer_patient_view, name='transfer_patient'),
    path('track/', views.track_patient_view, name='track_patient'),
    path('board/', views.calling_board_view, name='calling_board'),
    path('settings/', views.settings_view, name='settings'),
    path('problem/', views.problem_view, name='problem'),
    path('api/group-rooms/<int:group_id>/', views.get_group_rooms_view, name='get_group_rooms'),
]
