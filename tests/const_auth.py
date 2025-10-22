"""Authentication test constants.

This module contains fixtures for authentication flows including:
- SRP authentication (init and complete)
- 2FA validation
- Trust token management
- Session validation
"""

# SRP Authentication
SRP_INIT_OK = {
    "iteration": 20433,
    "salt": "0samK84bcBmkVsswOpZbZg==",
    "protocol": "s2k",
    "b": "STVHcWTN9YOYn4IgtIJ6UPdPbvzvL+zza/l+6yUHUtdEyxwzpB78y8wqZ8QWSbVqjBcpl32iEA4T3nYp0LWZ5hD3r3yIJFloXvX0kpBJkr\
        +Nh8EfHuW1V50A8riH6VWyuJ8m3JmOO7/xkNgP7je8GMpt/5f/7qE3AOj73e3JR0fzQ7IopdU0tlyVX0tD7T6wCyHS52GJWDdq1I2bgzurIK2\
        /ZjR/Hwzd/67oFQPtKQgjrSRaKo5MJEfDP7C9wOlXsZqbb7igX6PeZRWrfl+iQFaA/FVeWSngB07ja3wOryY9GsYO06ELGOaQ+MpsT7mouqrGT\
        fOJ0OMh9EgrkJEM6w==",
    "c": "e-1be-8746c235-b41c-11ef-bd17-c780acb4fe15:PRN",
}

# Authentication response
AUTH_OK = {"authType": "hsa2"}

# 2FA Trusted Devices
TRUSTED_DEVICE_1 = {
    "deviceType": "SMS",
    "areaCode": "",
    "phoneNumber": "*******58",
    "deviceId": "1",
}
TRUSTED_DEVICES = {"devices": [TRUSTED_DEVICE_1]}

# Verification Code Responses
VERIFICATION_CODE_OK = {"success": True}
VERIFICATION_CODE_KO = {"success": False}

# Trust Token Response (empty 204 response)
TRUST_TOKEN_OK = ""

# Session Validation Response (empty 204 response)
SESSION_VALID = ""
