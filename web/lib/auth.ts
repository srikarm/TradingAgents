import NextAuth, { type NextAuthConfig } from "next-auth";
import GitHub from "next-auth/providers/github";
import Credentials from "next-auth/providers/credentials";

const secret = process.env.NEXTAUTH_SECRET;
if (!secret) throw new Error("NEXTAUTH_SECRET is required");

const providers: NextAuthConfig["providers"] = [
  GitHub({
    clientId: process.env.AUTH_GITHUB_ID!,
    clientSecret: process.env.AUTH_GITHUB_SECRET!,
  }),
];

if (process.env.E2E_TEST_MODE === "1") {
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
  jwt: {
    // HS256 by default — matches server/app/auth.py
  },
  callbacks: {
    async jwt({ token, profile, user }) {
      // GitHub login (interactive): profile.id is numeric.
      if (profile && (profile as { id?: number | string }).id !== undefined) {
        token.sub = String((profile as { id: number | string }).id);
      } else if (user && process.env.E2E_TEST_MODE === "1") {
        // E2E credentials login: `user.id` is the supplied githubId.
        token.sub = String(user.id);
      }
      if (profile && (profile as { email?: string }).email) {
        token.email = (profile as { email: string }).email;
      } else if (user?.email) {
        token.email = user.email;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) (session.user as { githubId?: string }).githubId = token.sub;
      return session;
    },
  },
  secret,
};

export const { handlers, signIn, signOut, auth } = NextAuth(authConfig);
