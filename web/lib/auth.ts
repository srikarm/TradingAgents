import NextAuth, { type NextAuthConfig } from "next-auth";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";
import Credentials from "next-auth/providers/credentials";

const secret = process.env.NEXTAUTH_SECRET;
if (!secret) throw new Error("NEXTAUTH_SECRET is required");

const providers: NextAuthConfig["providers"] = [
  GitHub({
    clientId: process.env.AUTH_GITHUB_ID!,
    clientSecret: process.env.AUTH_GITHUB_SECRET!,
  }),
  Google({
    clientId: process.env.AUTH_GOOGLE_ID!,
    clientSecret: process.env.AUTH_GOOGLE_SECRET!,
  }),
];

// Dev-only credentials backdoor. Hard-fails if it ever sees production —
// guards against env-var drift (E2E_TEST_MODE=1 leaking into prod) per
// the design spec §3 and the 13 memory observations flagging this risk.
if (process.env.E2E_TEST_MODE === "1") {
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "E2E_TEST_MODE=1 cannot run with NODE_ENV=production. " +
        "This guards the credentials-provider backdoor from env-var drift."
    );
  }
  providers.push(
    Credentials({
      name: "e2e",
      credentials: { githubId: { label: "GitHub ID" } },
      async authorize(c) {
        if (!c?.githubId) return null;
        const id = String(c.githubId);
        return { id, email: `${id}@e2e.local` };
      },
    })
  );
}

export const authConfig: NextAuthConfig = {
  providers,
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  jwt: {
    // HS256 by default — matches server/app/auth.py
  },
  callbacks: {
    async jwt({ token, account, profile, user }) {
      if (account?.provider === "google" && profile) {
        const p = profile as { sub: string; email?: string };
        token.sub = String(p.sub);
        if (p.email) token.email = p.email;
        (token as { provider?: string }).provider = "google";
      } else if (account?.provider === "github" && profile) {
        const p = profile as { id: number | string; email?: string };
        token.sub = String(p.id);
        if (p.email) token.email = p.email;
        (token as { provider?: string }).provider = "github";
      } else if (user && process.env.E2E_TEST_MODE === "1") {
        token.sub = String(user.id);
        if (user.email) token.email = user.email;
        (token as { provider?: string }).provider = "e2e";
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) {
        const u = session.user as { providerId?: string; githubId?: string };
        u.providerId = token.sub;
        // Legacy alias — kept for code paths that still read githubId.
        // Remove in a later refactor once consumers migrate to providerId.
        u.githubId = token.sub;
      }
      return session;
    },
  },
  secret,
};

export const { handlers, signIn, signOut, auth } = NextAuth(authConfig);
