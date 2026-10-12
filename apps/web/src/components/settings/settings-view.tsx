"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Copy, ExternalLink, Lock } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";
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
  useMockOrders,
  useSeedMockOrders,
  useUpdateWorkspaceSettings,
  useWorkspaceSettings,
  type MockOrder,
  type WorkspaceSettings,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { initials } from "@/lib/utils";
import { HOST_MESSAGE_SOURCE, WIDGET_MESSAGE_SOURCE, type HostMessage } from "@/lib/widget/api";

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
          <ChatWidgetPanel settings={settings.data} canEdit={canEdit} />
          {canEdit && <DemoDataPanel />}
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
});

const originsSchema = z.object({
  allowed_origins: z
    .string()
    .refine(
      (v) => splitOrigins(v).every((line) => ORIGIN_RE.test(line)),
      "Put one origin on each line, like https://shop.example.com, with no path after it.",
    )
    .refine((v) => splitOrigins(v).length <= MAX_ORIGINS, `Add ${MAX_ORIGINS} origins or fewer.`),
});

type WorkspaceValues = z.infer<typeof workspaceSchema>;
type OriginsValues = z.infer<typeof originsSchema>;

function WorkspacePanel({ settings, canEdit }: { settings: WorkspaceSettings; canEdit: boolean }) {
  const update = useUpdateWorkspaceSettings();
  const form = useForm<WorkspaceValues>({
    resolver: zodResolver(workspaceSchema),
    values: { name: settings.name },
  });

  async function onSubmit(values: WorkspaceValues) {
    try {
      await update.mutateAsync({ name: values.name.trim() });
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
            Only owners and admins can edit workspace properties.
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

async function copyText(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied`);
  } catch {
    toast.error(`Couldn't copy the ${what.toLowerCase()}. Select it and copy it by hand.`);
  }
}

function ChatWidgetPanel({ settings, canEdit }: { settings: WorkspaceSettings; canEdit: boolean }) {
  const widgetKey = settings.widget_public_key;
  // Settings only render client-side, after the session guard.
  const appOrigin = typeof window === "undefined" ? "" : window.location.origin;
  const snippet = `<script src="${appOrigin}/widget.js" data-key="${widgetKey}" async></script>`;

  return (
    <GlassPanel id="chat-widget" aria-labelledby="widget-heading" className="flex scroll-mt-24 flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 id="widget-heading" className="font-display text-2xl font-bold tracking-tight text-bone">
          Chat widget
        </h2>
        <p className="max-w-2xl text-sm text-ash">
          Answers customer questions on your website from your knowledge base, with sources. Paste
          the snippet before the closing <code className="font-mono text-xs">&lt;/body&gt;</code>{" "}
          tag on each page.
        </p>
      </div>

      <div className="grid gap-8 xl:grid-cols-[1fr_auto]">
        <div className="flex min-w-0 flex-col gap-6">
          <div className="flex flex-col gap-2">
            <Label htmlFor="widget-snippet">Embed snippet</Label>
            <pre
              id="widget-snippet"
              tabIndex={0}
              className="overflow-x-auto rounded-[6px] border border-line bg-carbon-input p-3 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap text-bone focus-visible:ring-2 focus-visible:ring-ion focus-visible:outline-none"
            >
              {snippet}
            </pre>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" onClick={() => void copyText(snippet, "Snippet")} className="gap-1.5">
                <Copy className="size-3.5" aria-hidden />
                Copy snippet
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => void copyText(widgetKey, "Key")}
                className="gap-1.5"
              >
                <Copy className="size-3.5" aria-hidden />
                Copy key only
              </Button>
              <Button asChild size="sm" variant="ghost" className="gap-1.5">
                <Link href="/widget-demo" target="_blank" rel="noopener">
                  Try it on a demo page
                  <ExternalLink className="size-3.5" aria-hidden />
                </Link>
              </Button>
            </div>
          </div>

          <AllowedOriginsForm settings={settings} canEdit={canEdit} />
        </div>

        <WidgetPreview widgetKey={widgetKey} reloadKey={settings.allowed_origins.join(",")} />
      </div>
    </GlassPanel>
  );
}

function AllowedOriginsForm({ settings, canEdit }: { settings: WorkspaceSettings; canEdit: boolean }) {
  const update = useUpdateWorkspaceSettings();
  const form = useForm<OriginsValues>({
    resolver: zodResolver(originsSchema),
    values: { allowed_origins: settings.allowed_origins.join("\n") },
  });

  async function onSubmit(values: OriginsValues) {
    try {
      await update.mutateAsync({ allowed_origins: splitOrigins(values.allowed_origins) });
      toast.success("Allowed websites saved.");
    } catch {
      // Shown inline below the form via update.error.
    }
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
        <FormField
          control={form.control}
          name="allowed_origins"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Allowed websites</FormLabel>
              <FormControl>
                <Textarea
                  readOnly={!canEdit}
                  rows={3}
                  spellCheck={false}
                  placeholder={canEdit ? "https://shop.example.com" : "No websites added yet"}
                  className="font-mono text-xs"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                The widget only starts on these origins. One per line, like https://shop.example.com.
                {!canEdit && " Only owners and admins can change them."}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        {update.isError && <FormError>{errorMessage(update.error)}</FormError>}
        {canEdit && (
          <div>
            <Button type="submit" size="sm" disabled={!form.formState.isDirty || update.isPending}>
              {update.isPending ? "Saving…" : "Save websites"}
            </Button>
          </div>
        )}
      </form>
    </Form>
  );
}

/** The real widget in an iframe. Answers its handshake the way widget.js does on a website. */
function WidgetPreview({ widgetKey, reloadKey }: { widgetKey: string; reloadKey: string }) {
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const frame = frameRef.current;
      if (!frame || event.source !== frame.contentWindow || event.origin !== window.location.origin) {
        return;
      }
      const data = event.data as { source?: string; type?: string } | null;
      if (data?.source === WIDGET_MESSAGE_SOURCE && data.type === "ready") {
        const reply: HostMessage = { source: HOST_MESSAGE_SOURCE, type: "init" };
        frame.contentWindow?.postMessage(reply, window.location.origin);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium text-bone">Live preview</span>
      <div className="h-[560px] w-full overflow-hidden rounded-panel border border-line-strong bg-ink xl:w-[360px]">
        <iframe
          key={reloadKey}
          ref={frameRef}
          src={`/widget/${encodeURIComponent(widgetKey)}`}
          title="Chat widget preview"
          className="size-full"
        />
      </div>
      <p className="max-w-[360px] text-xs text-ash">
        This is the live widget, so questions here become real conversations. It runs on this
        app&apos;s origin, which must be allowed (or enabled for local development).
      </p>
    </div>
  );
}

const money = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });
const etaFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

const orderStatusTone = {
  processing: "neutral",
  shipped: "ion",
  delivered: "resolved",
  cancelled: "urgent",
} as const;

function DemoDataPanel() {
  const orders = useMockOrders(true);
  const seed = useSeedMockOrders();

  async function load() {
    try {
      const result = await seed.mutateAsync();
      toast.success(
        result.inserted > 0
          ? `Loaded ${result.inserted} sample orders.`
          : "Sample orders are already loaded.",
      );
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <GlassPanel aria-labelledby="demo-heading" className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex max-w-2xl flex-col gap-1">
          <h2 id="demo-heading" className="font-display text-2xl font-bold tracking-tight text-bone">
            Demo data
          </h2>
          <p className="text-sm text-ash">
            Sample orders stand in for your order system, so you can try order questions in the
            widget. Loading them again doesn&apos;t create duplicates.
          </p>
        </div>
        <Button type="button" onClick={() => void load()} disabled={seed.isPending}>
          {seed.isPending ? "Loading…" : "Load sample orders"}
        </Button>
      </div>

      {orders.isPending && <Skeleton className="h-32 w-full" />}
      {orders.isError && <FormError>{errorMessage(orders.error)}</FormError>}
      {orders.data && orders.data.length === 0 && (
        <p className="text-sm text-ash">No sample orders yet.</p>
      )}
      {orders.data && orders.data.length > 0 && <OrdersTable orders={orders.data} />}
    </GlassPanel>
  );
}

function OrdersTable({ orders }: { orders: MockOrder[] }) {
  return (
    <div className="overflow-x-auto rounded-[6px] border border-line">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">Sample orders</caption>
        <thead className="border-b border-line bg-carbon-input text-xs text-ash">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Order</th>
            <th scope="col" className="px-3 py-2 font-medium">Customer</th>
            <th scope="col" className="px-3 py-2 font-medium">Status</th>
            <th scope="col" className="px-3 py-2 font-medium">Carrier</th>
            <th scope="col" className="px-3 py-2 font-medium">ETA</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {orders.map((o) => (
            <tr key={o.id}>
              <td className="px-3 py-2 font-mono text-xs text-bone">{o.order_number}</td>
              <td className="px-3 py-2 text-ash">{o.contact_email}</td>
              <td className="px-3 py-2">
                <StatusChip tone={orderStatusTone[o.status]}>
                  {o.status.charAt(0).toUpperCase() + o.status.slice(1)}
                </StatusChip>
              </td>
              <td className="px-3 py-2 text-ash">
                {o.carrier ?? "–"}
                {o.tracking_number && (
                  <span className="block font-mono text-[11px]">{o.tracking_number}</span>
                )}
              </td>
              <td className="px-3 py-2 text-ash">
                {o.eta ? etaFormat.format(new Date(`${o.eta}T00:00:00`)) : "–"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-bone">
                {money.format(Number(o.total))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
