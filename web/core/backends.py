from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

class EmailOrUsernameModelBackend(ModelBackend):
    """
    This is a ModelBacked that allows authentication with either a username or an email address.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        print(f"DEBUG: EmailOrUsernameModelBackend called with username={username}")
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        
        if not username:
            return None

        try:
            # Check if the username is an email address
            if '@' in username:
                user = User.objects.get(email=username)
                print(f"DEBUG: Found user by email: {user}")
            else:
                user = User.objects.get(username=username)
                print(f"DEBUG: Found user by username: {user}")
        except User.DoesNotExist:
            print("DEBUG: User does not exist")
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user (#20760).
            User().set_password(password)
            return None
        
        if user.check_password(password):
            print("DEBUG: Password check passed")
            if self.user_can_authenticate(user):
                print("DEBUG: User can authenticate")
                return user
            else:
                print("DEBUG: User cannot authenticate (inactive?)")
        else:
            print("DEBUG: Password check failed")
        return None
