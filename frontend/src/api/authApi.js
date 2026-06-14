import { apiRequest } from "./api";

export function loginUser(loginData) {
  return apiRequest("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(loginData),
  });
}

export function signupUser(signupData) {
  return apiRequest("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify(signupData),
  });
}

export function registerUser(registerData) {
  return apiRequest("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(registerData),
  });
}