from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils.translation import gettext_lazy as _
# Create your models here.


class CustomUserManager(BaseUserManager):
    '''Manager for user'''
    def create_user(self, email, password, **extra_fields):
        '''Create and save new user'''
        if not email:
            raise ValueError('email must be available')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extrafields):
        '''Create and save new super user'''
        user = self.create_user(email=email, password=password)
        user.is_superuser = True
        user.is_staff = True
        user.save(using=self._db)

        return user


class CustomUser(AbstractBaseUser, PermissionsMixin):
    '''Custom django user db model'''
    email = models.EmailField(_('email address'), unique=True)
    otp = models.IntegerField(blank=True, null=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255, blank=True, null=True)
    individual_url = models.CharField(max_length=255, blank=True, null=True)
    business = models.BooleanField(default=False, blank=True, null=True)
    individual = models.BooleanField(default=False, blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    accepted_terms = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # user manager
    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []


class Token(models.Model):
    user_id = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='signin_user')
    access = models.TextField()
    refresh = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class OTP(models.Model):
    user_id = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='user_otp')
    generated_otp = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
