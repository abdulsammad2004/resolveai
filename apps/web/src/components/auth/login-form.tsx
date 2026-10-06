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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-provider";

const loginSchema = z.object({
  email: z.email("Enter your email address, like you@company.com."),
  password: z.string().min(1, "Enter your password."),
});

type LoginValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { login } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  async function onSubmit(values: LoginValues) {
    setFormError(null);
    try {
      // On success the (auth) layout redirects to ?next= or the dashboard.
      await login(values.email, values.password);
    } catch (err) {
      setFormError(errorMessage(err));
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold sm:text-3xl">Welcome back</h1>
        <p className="text-mist-dim">Log in to review drafts and keep your queue moving.</p>
      </header>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
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
                  <Input type="password" autoComplete="current-password" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormError>{formError}</FormError>

          <Button type="submit" size="lg" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? "Logging in…" : "Log in"}
          </Button>
        </form>
      </Form>

      <p className="text-mist-dim">
        New to ResolveAI?{" "}
        <Link href="/signup" className="font-medium text-seafoam underline-offset-4 hover:underline">
          Set up a workspace
        </Link>
      </p>
    </div>
  );
}
