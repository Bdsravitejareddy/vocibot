import { apiRequest } from "../api-base";

export type Role = "admin" | "clinician";

export type User = { id: string; username: string; display_name: string; role: Role; is_active: boolean; must_change_password: boolean; created_at: string; last_login_at: string | null; locked: boolean };

export type SecurityEvent = { id: string; occurred_at: string; event: string; username: string | null; actor_user_id: string | null; subject_user_id: string | null; ip_address: string | null; detail: Record<string, unknown> };

const quiet = { redirectOnUnauthorised: false };

export const getAuthStatus = () => apiRequest<{ setup_required: boolean; user: User | null }>("/api/auth/status", quiet);
export const signIn = (username: string, password: string) => apiRequest<{ user: User }>("/api/auth/login", { ...quiet, method: "POST", body: JSON.stringify({ username, password }) });
export const completeSetup = (input: { username: string; display_name: string; password: string }) => apiRequest<{ user: User }>("/api/auth/setup", { ...quiet, method: "POST", body: JSON.stringify(input) });
export const signOut = () => apiRequest<void>("/api/auth/logout", { ...quiet, method: "POST" });
export const changePassword = (current_password: string, new_password: string) => apiRequest<void>("/api/auth/password", { method: "POST", body: JSON.stringify({ current_password, new_password }) });

export const listUsers = () => apiRequest<User[]>("/api/admin/users");
export const createUser = (input: { username: string; display_name: string; password: string; role: Role; must_change_password: boolean }) => apiRequest<User>("/api/admin/users", { method: "POST", body: JSON.stringify(input) });
export const updateUser = (id: string, input: Partial<Pick<User, "display_name" | "role" | "is_active">>) => apiRequest<User>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(input) });
export const resetPassword = (id: string, new_password: string) => apiRequest<void>(`/api/admin/users/${id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password, must_change_password: true }) });
export const listSecurityEvents = () => apiRequest<SecurityEvent[]>("/api/admin/security-events");
