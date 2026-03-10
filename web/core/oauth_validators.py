from oauth2_provider.oauth2_validators import OAuth2Validator


class CustomOIDCValidator(OAuth2Validator):
    """
    Custom OAuth2/OIDC validator that includes user profile claims in ID tokens
    and UserInfo responses for LibreChat (and other OIDC clients).
    """

    def get_additional_claims(self, request):
        user = request.user
        return {
            'email': user.email,
            'email_verified': True,
            'name': user.get_full_name() or user.username,
            'preferred_username': user.username,
            'given_name': user.first_name,
            'family_name': user.last_name,
        }

    def get_userinfo_claims(self, request):
        claims = super().get_userinfo_claims(request)
        claims.update(self.get_additional_claims(request))
        return claims
