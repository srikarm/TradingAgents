// web/app/login/SignInForm.tsx
"use client";

import ProviderButton from "@/components/ProviderButton";

const ERROR_MESSAGES: Record<string, string> = {
  OAuthAccountNotLinked:
    "An account with this email already exists with a different sign-in method. Try signing in with your original provider.",
  AccessDenied: "Sign-in was cancelled or denied.",
  Configuration: "Sign-in is misconfigured. Please contact the administrator.",
  Verification: "The sign-in link is no longer valid. Please request a new one.",
};

function friendlyError(code: string | undefined): string | null {
  if (!code) return null;
  return ERROR_MESSAGES[code] ?? `Sign-in failed (${code}). Please try again.`;
}

interface Props {
  callbackUrl?: string;
  error?: string;
}

export default function SignInForm({ callbackUrl, error }: Props) {
  const errorMessage = friendlyError(error);

  return (
    <div className="space-y-2">
      {errorMessage && (
        <div
          role="alert"
          className="mb-3 rounded-md border border-brand/30 bg-brand/5 px-3 py-2 text-xs text-brand"
        >
          {errorMessage}
        </div>
      )}
      <ProviderButton provider="github" callbackUrl={callbackUrl} />
      <ProviderButton provider="google" callbackUrl={callbackUrl} />
    </div>
  );
}
