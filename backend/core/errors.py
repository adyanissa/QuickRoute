from fastapi import status


BUILDING_NOT_FOUND = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "Building not found"
}

ROOM_NOT_FOUND = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "Room not found"
}

START_NODE_NOT_FOUND = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "Start node not found"
}

END_NODE_NOT_FOUND = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "End node not found"
}

NO_ROUTE_FOUND = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "No route found"
}

INVALID_CREDENTIALS = {
    "status_code": status.HTTP_401_UNAUTHORIZED,
    "detail": "Invalid email or password"
}

EMAIL_ALREADY_EXISTS = {
    "status_code": status.HTTP_409_CONFLICT,
    "detail": "Email already exists"
}

USER_NOT_FOUND = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "User not found"
}

INVALID_INVITATION_CODE = {
    "status_code": status.HTTP_404_NOT_FOUND,
    "detail": "Invalid invitation code"
}

INVITATION_CODE_ALREADY_USED = {
    "status_code": status.HTTP_400_BAD_REQUEST,
    "detail": "Invitation code already used"
}

INVITATION_CODE_REQUIRED = {
    "status_code": status.HTTP_400_BAD_REQUEST,
    "detail": "Invitation code is required"
}