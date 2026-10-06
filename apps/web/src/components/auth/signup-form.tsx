"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormError } from "@/components/auth/form-error";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-provider";

const signupSchema = z.object({
  full_name: z.string().trim().min(1, "Enter your full name.").max(200),
  email: z.email("Enter your email address, like you@company.com."),
  password: z
    .string()
    .min(8, "Use at least 8 characters.")
    .max(256, "Use 256 characters or fewer."),
  workspace_name: z.string().trim().min(1, "Name your workspace.").max(200),
});

type SignupValues = z.infer<typeof signupSchema>;

export function SignupForm() {
  const { signup } = useAuth();
  const [formError, setFormError] = useState<{ message: string; emailTaken: boolean } | null>(
    null,
  );
  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: { full_name: "", email: "", password: "", workspace_name: "" },
  });

  async function onSubmit(values: SignupValues) {
    setFormError(null);
    try {
      // On success the (auth) layout redirects to the dashboard.
      await signup(values);
    } catch (err) {
      setFormError({
        message: errorMessage(err),
        emailTaken: err instanceof ApiError && err.status === 409,
      });
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold sm:text-3xl">Set up your support workspace</h1>
        <p className="text-mist-dim">You&apos;ll be the owner. Invite your team once you&apos;re in.</p>
      </header>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormField
            control={form.control}
            name="full_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Full name</FormLabel>
                <FormControl>
                  <Input autoComplete="name" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Work email</FormLabel>
                <FormControl>
                  <Input type="email" autoComplete="email" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Password</FormLabel>
                <FormControl>
                  <Input type="password" autoComplete="new-password" {...field} />
                </FormControl>
                <FormDescription>At least 8 characters.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="workspace_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Workspace name</FormLabel>
                <FormControl>
                  <Input autoComplete="organization" placeholder="Acme Support" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {formError && (
            <FormError>
              {formError.emailTaken ? (
                <>
                  That email is already registered.{" "}
                  <Link href="/login" className="font-medium text-seafoam underline underline-offset-4">
                    Log in instead.
                  </Link>
                </>
              ) : (
                formError.message
              )}
            </FormError>
          )}

          <Button type="submit" size="lg" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? "Creating workspace…" : "Create workspace"}
          </Button>
        </form>
      </Form>

      <p className="text-mist-dim">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-seafoam underline-offset-4 hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
