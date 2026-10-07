"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Copy, Lock } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormError } from "@/components/auth/form-error";
import { GlassPanel } from "@/components/glass-panel";
import { PageHeader } from "@/components/page-header";
import { StatusChip, roleLabel, roleTone } from "@/components/status-chip";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/errors";
import {
  useMembers,
  useUpdateWorkspaceSettings,
  useWorkspaceSettings,
  type WorkspaceSettings,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { initials } from "@/lib/utils";

export function SettingsView() {
  const { role } = useAuth();
  const settings = useWorkspaceSettings();
  const canEdit = role === "owner" || role === "admin";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Settings" description="Your workspace, your chat widget and your team." />

      {settings.isPending && (
        <GlassPanel>
          <p className="text-mist-dim" role="status">
            Loading workspace settings…
          </p>
        </GlassPanel>
      )}
      {settings.isError && (
        <GlassPanel>
          <FormError>{errorMessage(settings.error)}</FormError>
        </GlassPanel>
      )}
      {settings.data && (
        <>
          <WorkspacePanel settings={settings.data} canEdit={canEdit} />
          <WidgetKeyPanel widgetKey={settings.data.widget_public_key} />
        </>
      )}
      <MembersPanel />
    </div>
  );
}

const ORIGIN_RE = /^https?:\/\/[^\s/?#@]+\/?$/i;
const MAX_ORIGINS = 50;

function splitOrigins(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

const workspaceSchema = z.object({
  name: z.string().trim().min(1, "Give your workspace a name.").max(200, "Use 200 characters or fewer."),
  allowed_origins: z
    .string()
    .refine(
      (v) => splitOrigins(v).every((line) => ORIGIN_RE.test(line)),
      "Put one origin on each line, like https://shop.example.com, with no path after it.",
    )
    .refine((v) => splitOrigins(v).length <= MAX_ORIGINS, `Add ${MAX_ORIGINS} origins or fewer.`),
});

type WorkspaceValues = z.infer<typeof workspaceSchema>;

function WorkspacePanel({ settings, canEdit }: { settings: WorkspaceSettings; canEdit: boolean }) {
  const update = useUpdateWorkspaceSettings();
  const form = useForm<WorkspaceValues>({
    resolver: zodResolver(workspaceSchema),
    // `values` re-syncs the form whenever the saved settings change.
    values: {
      name: settings.name,
      allowed_origins: settings.allowed_origins.join("\n"),
    },
  });

  async function onSubmit(values: WorkspaceValues) {
    try {
      await update.mutateAsync({
        name: values.name.trim(),
        allowed_origins: splitOrigins(values.allowed_origins),
      });
      toast.success("Workspace settings saved.");
    } catch {
      // Shown inline below the form via update.error.
    }
  }

  return (
    <GlassPanel aria-labelledby="workspace-heading" className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <h2 id="workspace-heading" className="text-xl font-semibold">
          Workspace
        </h2>
        {!canEdit && (
          <p className="flex items-start gap-2 text-mist-dim">
            <Lock className="mt-1 size-4 shrink-0" aria-hidden />
            Only owners and admins can change these settings, because they control who can reach
            your chat widget. Ask one of them if something needs updating.
          </p>
        )}
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex max-w-xl flex-col gap-5">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Workspace name</FormLabel>
                <FormControl>
                  <Input readOnly={!canEdit} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="allowed_origins"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Allowed origins</FormLabel>
                <FormControl>
                  <Textarea
                    readOnly={!canEdit}
                    rows={3}
                    spellCheck={false}
                    placeholder={canEdit ? "https://shop.example.com" : "No origins added yet"}
                    className="font-mono text-sm"
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  Websites allowed to load your chat widget. Put one on each line.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />

          {update.isError && <FormError>{errorMessage(update.error)}</FormError>}

          {canEdit && (
            <div>
              <Button type="submit" disabled={!form.formState.isDirty || update.isPending}>
                {update.isPending ? "Saving…" : "Save changes"}
              </Button>
            </div>
          )}
        </form>
      </Form>
    </GlassPanel>
  );
}

function WidgetKeyPanel({ widgetKey }: { widgetKey: string }) {
  async function copyKey() {
    try {
      await navigator.clipboard.writeText(widgetKey);
      toast.success("Copied");
    } catch {
      toast.error("Couldn't copy the key. Select it and copy it by hand.");
    }
  }

  return (
    <GlassPanel aria-labelledby="widget-heading" className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <h2 id="widget-heading" className="text-xl font-semibold">
          Chat widget key
        </h2>
        <p className="max-w-2xl text-mist-dim">
          Your chat widget uses this public key to send customer messages to this workspace. It
          only works on the allowed origins above.
        </p>
      </div>
      <div className="flex max-w-2xl flex-col gap-2">
        <Label htmlFor="widget-key">Public key</Label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input
            id="widget-key"
            readOnly
            value={widgetKey}
            className="font-mono text-sm"
            onFocus={(e) => e.currentTarget.select()}
          />
          <Button type="button" variant="secondary" onClick={copyKey} className="shrink-0">
            <Copy aria-hidden />
            Copy key
          </Button>
        </div>
      </div>
    </GlassPanel>
  );
}

function MembersPanel() {
  const { user } = useAuth();
  const members = useMembers();

  return (
    <GlassPanel aria-labelledby="members-heading" className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <h2 id="members-heading" className="text-xl font-semibold">
          Members
        </h2>
        <p className="text-mist-dim">Everyone who can work in this workspace, and their role.</p>
      </div>

      {members.isPending && (
        <p className="text-mist-dim" role="status">
          Loading members…
        </p>
      )}
      {members.isError && <FormError>{errorMessage(members.error)}</FormError>}
      {members.data && (
        <ul className="flex flex-col">
          {members.data.map((member, i) => (
            <li key={member.user_id}>
              {i > 0 && <Separator />}
              <div className="flex items-center gap-3 py-3.5">
                <Avatar>
                  <AvatarFallback>{initials(member.full_name)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">
                    {member.full_name}
                    {member.user_id === user?.id && (
                      <span className="font-normal text-mist-dim"> (you)</span>
                    )}
                  </p>
                  <p className="truncate text-sm text-mist-dim">{member.email}</p>
                </div>
                <StatusChip tone={roleTone[member.role]}>{roleLabel[member.role]}</StatusChip>
              </div>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
