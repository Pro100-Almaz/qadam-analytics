# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.conf import settings
import os

from .models import CustomUser
from apps.home.models import ClassRoom

class CustomUserAvatarTests(TestCase):
    def setUp(self):
        # Create a test image file
        self.test_image = SimpleUploadedFile(
            name='test_image.jpg',
            content=b'',  # Empty file content
            content_type='image/jpeg'
        )
        
        # Create a test user
        self.user_data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test',
            'last_name': 'User',
            'role': CustomUser.ROLE_STUDENT,
        }
        
        self.user = CustomUser.objects.create_user(**self.user_data)
        
        # Create a test client
        self.client = Client()

    def test_avatar_upload_path(self):
        """Test that avatar files are saved with correct path structure"""
        self.user.avatar = self.test_image
        self.user.save()
        
        # Check if the avatar path contains the expected structure
        self.assertTrue(self.user.avatar.name.startswith('avatars/'))
        self.assertTrue(self.user.avatar.name.endswith('.jpg'))

    def test_avatar_url_generation(self):
        """Test that avatar URLs are generated correctly"""
        self.user.avatar = self.test_image
        self.user.save()
        
        # Check if the avatar URL is generated correctly
        self.assertTrue(self.user.avatar.url.startswith('https://'))
        self.assertTrue(self.user.avatar.url.endswith('.jpg'))

    def test_avatar_upload_via_registration(self):
        """Test avatar upload during user registration"""
        registration_data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'newpass123',
            'password2': 'newpass123',
            'first_name': 'New',
            'last_name': 'User',
            'role': CustomUser.ROLE_STUDENT,
        }
        
        # Create a test image for registration
        test_image = SimpleUploadedFile(
            name='registration_image.jpg',
            content=b'',
            content_type='image/jpeg'
        )
        
        # Create a multipart form data dictionary
        form_data = registration_data.copy()
        form_data['avatar'] = test_image
        
        # Make the registration request
        response = self.client.post(
            reverse('register'),
            data=form_data,
            format='multipart'
        )
        
        # Check if the user was created
        self.assertEqual(response.status_code, 302)  # Redirect after successful registration
        
        # Verify the user exists and has an avatar
        new_user = CustomUser.objects.get(email='new@example.com')
        self.assertTrue(hasattr(new_user, 'avatar'))
        self.assertTrue(new_user.avatar.name.startswith('avatars/'))

    def test_avatar_update(self):
        """Test updating an existing user's avatar"""
        # First set an initial avatar
        self.user.avatar = self.test_image
        self.user.save()
        initial_avatar_path = self.user.avatar.name
        
        # Create a new test image
        new_image = SimpleUploadedFile(
            name='new_image.jpg',
            content=b'',
            content_type='image/jpeg'
        )
        
        # Update the avatar
        self.user.avatar = new_image
        self.user.save()
        
        # Check if the avatar was updated
        self.assertNotEqual(self.user.avatar.name, initial_avatar_path)
        self.assertTrue(self.user.avatar.name.startswith('avatars/'))
        self.assertTrue(self.user.avatar.name.endswith('.jpg'))

    def test_avatar_removal(self):
        """Test removing a user's avatar"""
        # First set an avatar
        self.user.avatar = self.test_image
        self.user.save()
        
        # Remove the avatar
        self.user.avatar.delete()
        self.user.save()
        
        # Check if the avatar was removed
        self.assertFalse(self.user.avatar)
        self.assertFalse(hasattr(self.user, 'avatar') or self.user.avatar is None)

    def tearDown(self):
        # Clean up any test files
        if self.user.avatar:
            if os.path.isfile(self.user.avatar.path):
                os.remove(self.user.avatar.path)

