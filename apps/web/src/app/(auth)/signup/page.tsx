import type { Metadata } from "next";

import { SignupForm } from "@/components/auth/signup-form";

export const metadata: Metadata = { title: "Set up your workspace" };

export default function SignupPage() {
  return <SignupForm />;
}
