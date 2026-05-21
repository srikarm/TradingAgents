// web/components/ProviderButton.tsx
"use client";

import { signIn } from "next-auth/react";

type Provider = "github" | "google";

interface Props {
  provider: Provider;
  callbackUrl?: string;
  disabled?: boolean;
}

const LABEL: Record<Provider, string> = {
  github: "Continue with GitHub",
  google: "Continue with Google",
};

const Icon = ({ provider }: { provider: Provider }) => {
  if (provider === "github") {
    return (
      <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.5-1.4-1.3-1.8-1.3-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.4 1 .1-.8.4-1.3.8-1.6-2.6-.3-5.4-1.3-5.4-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.7 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.4 5.9.4.4.8 1.1.8 2.3v3.4c0 .3.2.7.8.6A12 12 0 0 0 12 .3" />
      </svg>
    );
  }
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M21.4 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.3c-.2 1.2-.9 2.3-2 3v2.4h3.2c1.9-1.7 3-4.3 3-7.2z" fill="#4285f4" />
      <path d="M12 22c2.7 0 5-.9 6.6-2.5l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3v2.6A10 10 0 0 0 12 22z" fill="#34a853" />
      <path d="M6.4 13.9A6 6 0 0 1 6 12c0-.7.1-1.3.4-1.9V7.5H3a10 10 0 0 0 0 9z" fill="#fbbc05" />
      <path d="M12 5.9a5.4 5.4 0 0 1 3.8 1.5l2.8-2.8A10 10 0 0 0 12 2a10 10 0 0 0-9 5.5l3.4 2.6c.8-2.4 3-4.2 5.6-4.2z" fill="#ea4335" />
    </svg>
  );
};

export default function ProviderButton({ provider, callbackUrl = "/history", disabled = false }: Props) {
  return (
    <button
      type="button"
      onClick={() => signIn(provider, { callbackUrl })}
      disabled={disabled}
      className="flex w-full items-center gap-2.5 rounded-lg border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-sm font-medium text-fg-primary transition hover:bg-white/[0.07] hover:border-white/15 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Icon provider={provider} />
      <span>{LABEL[provider]}</span>
    </button>
  );
}
