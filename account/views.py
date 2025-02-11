'''
Views for user API.
'''
import json
import requests
import threading

from django.db import transaction
from django.contrib.auth import authenticate
from django.conf import settings
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives

from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from account.models import Token, CustomUser, OTP
from notification.notify import notify_user

from .authentication import CustomAuthentication
from .utils import generate_otp, send_email

from account.serializers import (
        SignUpSerializer,
        SignInSerializer,
        ForgotPasswordSerializer,
        ProfileSerializer,
        ChangePasswordSerializer,
        OTPSerializer,
        ResendOTPSerializer
    )


class SignUpView(APIView):
    '''Creates a new user in database.'''
    serializer_class = SignUpSerializer

    def post(self, request):
        context = {}

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        context['status'] = 'success'
        context['message'] = 'Account created successfully.'
        context.update(serializer.data)

        return Response(context, status.HTTP_201_CREATED)


class SignInView(APIView):
    '''Sign in user with valid credential'''
    serializer_class = SignInSerializer
    auth = CustomAuthentication()

    def post(self, request):
        '''User validation and authentication.'''
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            username=serializer.validated_data['email'],
            password=serializer.validated_data['password']
        )

        if user is None:
            return Response({
                'status': 'error',
                'message': 'Invalid account credentials'
            }, status=400)

        access = self.auth.get_access_token({'user_id': user.id})
        refresh = self.auth.get_refresh_token()

        # check if user have prev tokens & then delete it
        Token.objects.filter(user_id=user).delete()

        # create tokens for user
        Token.objects.create(
            user_id=user,
            access=access,
            refresh=refresh
        )

        response = Response({
            'status': 'success',
            'access_token': access
        })

        # cookie setting
        response.set_cookie(
            'refresh_token', refresh, secure=True, samesite='None', max_age=86400
        )

        return response


class ForgotPasswordView(APIView):
    '''Send a custom email for user to reset password'''
    serializer_class = ForgotPasswordSerializer

    def post(self, request):
        '''A reset password mail is sent'''
        context = {}
        token = request.GET.get('token', 'None')
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            new_password = serializer.validated_data.get('new_password')
            domain = request.get_host()
            protocol = request.scheme

            url = f'{protocol}://{domain}/api/password_reset/confirm/'
            body = {
                "password": new_password,
                "token": token
            }
            headers = {
                'Content-Type': 'application/json'
            }
            response = requests.post(url, headers=headers, json=body)
            response = json.loads(response.text)

            if response.get('status') == 'OK':
                context['status'] = 'success'
                context['message'] = 'Password reset successful'
                return Response(context, status=status.HTTP_200_OK)

            elif response.get('detail'):
                context['status'] = 'error'
                context['message'] = 'Invalid token'
                return Response(context, status=status.HTTP_400_BAD_REQUEST)

            else:
                context['status'] = 'error'
                context['message'] = 'Invalid'
                return Response(context, status=status.HTTP_400_BAD_REQUEST)

        context['status'] = 'error'
        context.update(serializer.errors)
        return Response(context, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    '''Change password for user'''
    authentication_classes = [CustomAuthentication,]
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        '''confirm old password and saves new password'''
        context = {}
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            old_password = serializer.validated_data.get('old_password')
            new_password = serializer.validated_data.get('new_password')

            user = request.user
            if user.check_password(old_password):
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)  # To update session after password change

                context['status'] = 'success'
                context['message'] = 'Password changed successfully.'
                notify_user(request.user, 'password-success', context['message'])
                return Response(context, status=status.HTTP_200_OK)

            context['status'] = 'error'
            context['message'] = 'Incorrect old password.'
            notify_user(request.user, 'password-failure', context['message'])
            return Response(context, status=status.HTTP_400_BAD_REQUEST)

        context['status'] = 'error'
        context.update(serializer.errors)
        notify_user(request.user, 'password-failure', 'Password failed to change')
        return Response(context, status=status.HTTP_400_BAD_REQUEST)


class ResendOTPView(APIView):
    '''Send new OTP to user'''
    serializer_class = ResendOTPSerializer

    def post(self, request):
        context = {}
        otp = generate_otp()

        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data.get('email')
            try:
                user_otp = OTP.objects.get(user_id__email=email)
            except OTP.DoesNotExist:
                context['status'] = 'error'
                context['message'] = 'Email not associated to user or otp'
                return Response(context, status=status.HTTP_404_NOT_FOUND)

            user_otp.generated_otp = otp
            user_otp.save()

            data = {
                'email': email,
                'otp': otp
            }

            subject = "OTP Resent by {title}".format(title="Invoice Pulse")
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email,]
            email_template = render_to_string('account/otp.html', data)

            try:
                send_email(subject, email_template, from_email, recipient_list)
                context['status'] = 'success'
                context['message'] = 'OTP sent successful'
                notify_user(request.user, 'otp-success', context['message'])
                return Response(context, status=status.HTTP_200_OK)

            except Exception as e:
                context['status'] = 'error'
                context['message'] = f'Email sending error: {e}'
                notify_user(request.user, 'email-failure', 'OTP email failed to send')
                return Response(context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        context['status'] = 'error'
        context.update(serializer.errors)
        notify_user(request.user, 'otp-failure', 'Failed to send OTP')
        return Response(context, status=status.HTTP_400_BAD_REQUEST)


class ValidateOTPView(APIView):
    '''Validates OTP provided by user'''
    serializer_class = OTPSerializer

    def post(self, request):
        context = {}
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            otp = int(serializer.validated_data.get('otp'))

            try:
                user_otp = OTP.objects.get(generated_otp=otp)
            except OTP.DoesNotExist:
                context['status'] = 'error'
                context['message'] = 'Invalid OTP'
                return Response(context, status=status.HTTP_404_NOT_FOUND)

            otp_time = timezone.now() - user_otp.updated_at
            exp_time = timezone.timedelta(minutes=5)

            if otp_time > exp_time:
                context['status'] = 'error'
                context['message'] = 'Expired OTP'
                return Response(context, status=status.HTTP_400_BAD_REQUEST)

            if user_otp.generated_otp == otp:
                user_otp.generated_otp = None  # Reset the OTP field after successful validation
                user_otp.save()

            with transaction.atomic():
                user_otp.user_id.email_verified = True
                user_otp.user_id.save()

            context['status'] = 'success'
            context['message'] = 'OTP validated successful'
            return Response(context, status=status.HTTP_200_OK)

        context['status'] = 'error'
        context.update(serializer.errors)
        return Response(context, status=status.HTTP_400_BAD_REQUEST)


class RefreshTokenView(APIView):
    '''Provides a new access token for user.'''

    auth = CustomAuthentication()

    def get(self, request):
        '''Creates new tokens for user with valid refresh token.'''
        refresh_token_cookie = request.COOKIES.get('refresh_token') # get cookies

        try:
            active_token = Token.objects.get(refresh=refresh_token_cookie)
        except Token.DoesNotExist:
            return Response({
                'status': 'error',
                'message': 'Refresh token not found.'
            }, status=400)

        if not self.auth.verify_token(refresh_token_cookie):
            return Response({
                'status': 'error',
                'message': 'Refresh token invalid or expired.'
            }, status=400)

        access = self.auth.get_access_token({'user_id': active_token.id})
        refresh = self.auth.get_refresh_token()

        active_token.access = access
        active_token.refresh = refresh

        active_token.save()

        response = Response({
            'status': 'success',
            'access_token': access
        })

        # cookie setting
        response.set_cookie(
            'refresh_token', refresh, secure=True, samesite='None', max_age=86400
        )

        return response


class ProfileView(APIView):
    '''Returns user profile.'''
    authentication_classes = [CustomAuthentication,]
    permission_classes = [IsAuthenticated, ]
    serializer_class = ProfileSerializer

    def get(self, request):
        context = {}
        serializer = self.serializer_class(request.user)
        context['status'] = 'success'
        context.update(serializer.data)

        return Response(context)

    def put(self, request):
        context = {}
        serializer = self.serializer_class(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            context['status'] = 'success'
            context.update(serializer.data)
            notify_user(request.user, 'profile-success', 'Profile updated successful')
            return Response(context, status.HTTP_200_OK)

        context['status'] = 'error'
        context.update(serializer.errors)
        notify_user(request.user, 'profile-failure', 'Profile failed to update')

        return Response(context, status.HTTP_400_BAD_REQUEST)
