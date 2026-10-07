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
import { Skeleton } from "@/components/ui/skeleton";
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
    <div className="flex flex-col gap-6 max-w-5xl mx-auto">
      <PageHeader title="Settings" description="Manage your workspace, embeddable chat widget, and team access." />

      {settings.isPending && (
        <>
          <GlassPanel aria-busy="true" aria-label="Loading workspace settings" className="flex flex-col gap-5">
            <Skeleton className="h-7 w-48" />
            <Skeleton className="h-10 w-full max-w-xl" />
            <Skeleton className="h-20 w-full max-w-xl" />
          </GlassPanel>
          <GlassPanel aria-busy="true" aria-label="Loading widget key" className="flex flex-col gap-4">
            <Skeleton className="h-7 w-56" />
            <Skeleton className="h-10 w-full max-w-2xl" />
          </GlassPanel>
        </>
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
      <div className="flex flex-col gap-1">
        <h2 id="workspace-heading" className="font-display text-2xl font-bold tracking-tight text-bone">
          Workspace profile
        </h2>
        {!canEdit && (
          <p className="flex items-start gap-2 text-xs text-ash">
            <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Only owners and admins can edit workspace properties and allowed widget origins.
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
                <FormLabel>Allowed web origins</FormLabel>
                <FormControl>
                  <Textarea
                    readOnly={!canEdit}
                    rows={3}
                    spellCheck={false}
                    placeholder={canEdit ? "https://shop.example.com" : "No origins added yet"}
                    className="font-mono text-xs"
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  Websites allowed to embed and initialize your AI chat widget. One domain per line.
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
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Couldn't copy the key. Select it and copy it by hand.");
    }
  }

  return (
    <GlassPanel aria-labelledby="widget-heading" className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h2 id="widget-heading" className="font-display text-2xl font-bold tracking-tight text-bone">
          Chat widget public key
        </h2>
        <p className="max-w-2xl text-sm text-ash">
          Embed this public key into your website client SDK to identify and scope conversations to this tenant.
        </p>
      </div>
      <div className="flex max-w-2xl flex-col gap-2">
        <Label htmlFor="widget-key">Public key</Label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input
            id="widget-key"
            readOnly
            value={widgetKey}
            className="font-mono text-xs text-bone"
            onFocus={(e) => e.currentTarget.select()}
          />
          <Button type="button" variant="secondary" onClick={copyKey} className="shrink-0 gap-1.5">
            <Copy className="size-3.5" aria-hidden />
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
      <div className="flex flex-col gap-1">
        <h2 id="members-heading" className="font-display text-2xl font-bold tracking-tight text-bone">
          Workspace members
        </h2>
        <p className="text-sm text-ash">Authorized team members with role-based workspace permissions.</p>
      </div>

      {members.isPending && (
        <ul aria-busy="true" aria-label="Loading members" className="flex flex-col gap-4">
          {[0, 1].map((i) => (
            <li key={i} className="flex items-center gap-3">
              <Skeleton className="size-9 rounded-full" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-3.5 w-40" />
                <Skeleton className="h-3 w-56" />
              </div>
            </li>
          ))}
        </ul>
      )}
      {members.isError && <FormError>{errorMessage(members.error)}</FormError>}
      {members.data && (
        <ul className="flex flex-col divide-y divide-line">
          {members.data.map((member) => (
            <li key={member.user_id} className="flex items-center justify-between py-3.5">
              <div className="flex items-center gap-3">
                <Avatar className="size-9 border border-line bg-carbon-elevated text-xs font-semibold text-bone">
                  <AvatarFallback>{initials(member.full_name)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-bone">
                    {member.full_name}
                    {member.user_id === user?.id && (
                      <span className="font-normal text-ash"> (you)</span>
                    )}
                  </p>
                  <p className="truncate text-xs text-ash">{member.email}</p>
                </div>
              </div>
              <StatusChip tone={roleTone[member.role]}>{roleLabel[member.role]}</StatusChip>
            </li>
          ))}
        </ul>
      )}
    </GlassPanel>
  );
}
