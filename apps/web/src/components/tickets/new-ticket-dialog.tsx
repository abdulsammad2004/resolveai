"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
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
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/errors";
import { useCreateTicket } from "@/lib/api/queries";

const schema = z.object({
  subject: z.string().trim().min(1, "Give the ticket a subject.").max(200, "Use 200 characters or fewer."),
  description: z
    .string()
    .trim()
    .min(1, "Describe what the customer needs.")
    .max(5000, "Use 5,000 characters or fewer."),
  contact_email: z.union([z.literal(""), z.email("Enter a valid email, or leave it empty.")]),
});

type Values = z.infer<typeof schema>;

export function NewTicketDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (id: string) => void;
}) {
  const create = useCreateTicket();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { subject: "", description: "", contact_email: "" },
  });

  async function onSubmit(values: Values) {
    try {
      const ticket = await create.mutateAsync({
        subject: values.subject,
        description: values.description,
        contact_email: values.contact_email || null,
      });
      toast.success("Ticket created and classified.");
      form.reset();
      onOpenChange(false);
      onCreated(ticket.id);
    } catch {
      // Shown inline via create.error.
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) create.reset();
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-ink/80 duration-150 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col gap-5 overflow-y-auto rounded-panel border border-line-strong bg-carbon-elevated p-6 text-bone shadow-2xl duration-150 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <Dialog.Title className="font-display text-2xl font-bold tracking-tight">New ticket</Dialog.Title>
              <Dialog.Description className="text-sm text-ash">
                Log a request from email, phone or anywhere else. It&apos;s classified like a chat
                message to set its intent and priority.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close" className="-mt-1 -mr-2 shrink-0">
                <X className="size-4" aria-hidden />
              </Button>
            </Dialog.Close>
          </div>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
              <FormField
                control={form.control}
                name="subject"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Subject</FormLabel>
                    <FormControl>
                      <Input placeholder="Charged twice for order RA-10424" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea rows={5} placeholder="What the customer said and needs" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="contact_email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Contact email (optional)</FormLabel>
                    <FormControl>
                      <Input type="email" autoComplete="off" placeholder="customer@example.com" {...field} />
                    </FormControl>
                    <FormDescription>Links the ticket to this customer.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {create.isError && <FormError>{errorMessage(create.error)}</FormError>}
              <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
                <Dialog.Close asChild>
                  <Button type="button" variant="secondary">
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button type="submit" disabled={create.isPending}>
                  {create.isPending ? "Classifying…" : "Create ticket"}
                </Button>
              </div>
            </form>
          </Form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
