# Enabling 2FA on npm for Publishing

npm requires two-factor authentication (2FA) to publish scoped packages (`@username/package`).

## Steps to Enable 2FA

### Option 1: Web Interface (Recommended)

1. Go to [npmjs.com](https://www.npmjs.com) and sign in
2. Click your profile icon → **Account**
3. Go to **Two-Factor Authentication** section
4. Click **Enable 2FA**
5. Choose: **Auth and Publishes** (required for publishing)
6. Scan QR code with your authenticator app:
   - Google Authenticator
   - Authy
   - 1Password
   - etc.
7. Enter the 6-digit code to confirm
8. **Save your recovery codes** in a safe place!

### Option 2: CLI

```bash
npm profile enable-2fa auth-and-writes
```

This will:
1. Display a QR code in your terminal
2. Ask you to scan it with an authenticator app
3. Ask for a verification code

## After Enabling 2FA

Simply run:

```bash
npm publish --access public
```

npm will **automatically prompt** you for your 6-digit OTP code:
```
Enter OTP: ______
```

Enter the code from your authenticator app and press Enter.

## Recovery

If you lose access to your authenticator:
- Use the recovery codes you saved
- Contact npm support with account verification

## Why This is Required

npm enforces 2FA for scoped packages (@username/package) to prevent account hijacking and malicious package updates. This protects both you and your users.
