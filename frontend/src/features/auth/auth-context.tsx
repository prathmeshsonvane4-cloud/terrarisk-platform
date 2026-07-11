"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { clearSession, getSession, setSession, type Session } from "./session";

interface AuthContextValue {
  session: Session | null;
  /** False until the client has had a chance to read localStorage — the
   * auth guard must wait for this before deciding to redirect, otherwise
   * a real logged-in officer gets bounced to /login on every hard refresh. */
  isInitialized: boolean;
  login: (session: Session) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<Session | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);

  useEffect(() => {
    setSessionState(getSession());
    setIsInitialized(true);
  }, []);

  function login(newSession: Session) {
    setSession(newSession);
    setSessionState(newSession);
  }

  function logout() {
    clearSession();
    setSessionState(null);
  }

  return (
    <AuthContext.Provider value={{ session, isInitialized, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
