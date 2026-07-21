from django.contrib import admin

# Register your models here.
from .models import * 

# 2. Register your model here
admin.site.register(Patient)
admin.site.register(Room)
admin.site.register(PatientCondition)
admin.site.register(UserProfile)
admin.site.register(Speciality)
