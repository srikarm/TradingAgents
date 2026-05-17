import NextAuth, { type NextAuthConfig } from "next-auth";
import GitHub from "next-auth/providers/github";

const secret = process.env.NEXTAUTH_SECRET;
if (!secret) throw new Error("NEXTAUTH_SECRET is required");

export const authConfig: NextAuthConfig = {
  providers: [
    GitHub({
      clientId: process.env.AUTH_GITHUB_ID!,
      clientSecret: process.env.AUTH_GITHUB_SECRET!,
    }),
  ],
  session: { strategy: "jwt" },
  jwt: {
    // HS256 by default — matches server/app/auth.py
  },
  callbacks: {
    async jwt({ token, profile }) {
      // GitHub profile.id is the numeric user id (number); coerce to string
      if (profile && (profile as { id?: number | string }).id !== undefined) {
        token.sub = String((profile as { id: number | string }).id);
      }
      if (profile && (profile as { email?: string }).email) {
        token.email = (profile as { email: string }).email;
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
