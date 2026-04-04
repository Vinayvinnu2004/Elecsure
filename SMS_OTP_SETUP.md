# ElecSure SMS OTP Setup (Twilio)

ElecSure uses **Twilio** as its exclusive SMS provider for secure OTP delivery and real-time notifications.

---

## 🚀 Twilio Setup Guide

### 1. Get Your Credentials
1. **Sign Up**: Go to [https://www.twilio.com](https://www.twilio.com) and create an account.
2. **Dashboard**: Navigate to the Console Dashboard.
3. **Copy Credentials**:
   - `Account SID`
   - `Auth Token`
   - `Twilio Phone Number` (Buy one if you don't have one)

### 2. Update Your `.env` File
Add the following keys to your project root's `.env` file:

```env
# -- Twilio Settings --------
TWILIO_ACCOUNT_SID=ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1234567890
```

### 3. Verify Recipient Numbers (Trial Accounts ONLY)
If you are using a **Twilio Trial Account**:
- You can only send SMS to numbers you have manually verified in the Twilio Console.
- Go to **Phone Numbers → Verified Caller IDs** to add your own phone number for testing.

---

## 🛠️ Testing the Setup

### Debug Mode (Free)
Ensure `DEBUG=true` is set in your `.env`. 
The system will **print the SMS to the server console** instead of sending it via Twilio. This helps you verify the logic without using your Twilio credits.

### Live Mode (Production)
Set `DEBUG=false` in your `.env`.
1. Restart the server.
2. Try a registration or password reset.
3. Check the server logs for: `SMS sent via Twilio → +91... | SID: SM...`

---

## ❓ Troubleshooting

- **Error: "Twilio not configured"**: Double-check that your `.env` keys match the names above exactly.
- **Error: "The 'To' number is not verified"**: This means you are on a Twilio trial account and trying to send an SMS to a number that hasn't been added to your "Verified Caller IDs".
- **Formatting**: The system automatically adds the `+91` prefix for Indian numbers if you provide a 10-digit number.
