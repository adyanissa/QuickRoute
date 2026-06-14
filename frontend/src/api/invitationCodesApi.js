import { apiRequest } from "./api";

export function validateInvitationCode(code) {
  return apiRequest("/api/invitation-codes/validate", {
    method: "POST",
    body: JSON.stringify({
      code: code,
    }),
  });
}