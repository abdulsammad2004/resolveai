"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { roleLabel } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { useCreateWorkspace, useWorkspaces } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";

export function WorkspaceSwitcher() {
  const { workspace, role, switchWorkspace } = useAuth();
  const workspaces = useWorkspaces();
  const [creating, setCreating] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const openingCreate = useRef(false);

  if (!workspace || !role) return null;

  async function handleSwitch(id: string, name: string) {
    if (id === workspace?.id) return;
    try {
      await switchWorkspace(id);
      toast.success(`You're now working in ${name}.`);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  function closeCreate() {
    setCreating(false);
    triggerRef.current?.focus();
  }

  return (
    <div className="relative min-w-0">
      <DropdownMenu>
        <DropdownMenuTrigger
          ref={triggerRef}
          className="glass glass-interactive pressable flex h-11 max-w-full min-w-0 items-center gap-3 rounded-card px-3.5 text-left"
        >
          <span className="min-w-0">
            <span className="block truncate font-medium text-mist">{workspace.name}</span>
          </span>
          <span className="hidden text-sm text-mist-dim sm:inline">{roleLabel[role]}</span>
          <ChevronsUpDown className="size-4 shrink-0 text-mist-dim" aria-hidden />
          <span className="sr-only">Switch workspace</span>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className="w-72"
          onCloseAutoFocus={(event) => {
            // Let the create form take focus instead of the trigger.
            if (openingCreate.current) {
              event.preventDefault();
              openingCreate.current = false;
            }
          }}
        >
          <DropdownMenuLabel>Your workspaces</DropdownMenuLabel>
          <DropdownMenuGroup>
            {workspaces.isPending && (
              <DropdownMenuItem disabled>Loading workspaces…</DropdownMenuItem>
            )}
            {workspaces.isError && (
              <DropdownMenuItem disabled>Couldn&apos;t load your workspaces.</DropdownMenuItem>
            )}
            {workspaces.data?.map((ws) => {
              const current = ws.id === workspace.id;
              return (
                <DropdownMenuItem
                  key={ws.id}
                  onSelect={() => void handleSwitch(ws.id, ws.name)}
                  aria-current={current ? "true" : undefined}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{ws.name}</span>
                    <span className="block text-sm text-mist-dim">{roleLabel[ws.role]}</span>
                  </span>
                  {current && <Check className="text-seafoam" aria-label="Current workspace" />}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => {
              openingCreate.current = true;
              setCreating(true);
            }}
          >
            <Plus aria-hidden />
            Create workspace
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {creating && <CreateWorkspacePanel onClose={closeCreate} />}
    </div>
  );
}

const createSchema = z.object({
  name: z.string().trim().min(1, "Name your workspace.").max(200, "Use 200 characters or fewer."),
});

function CreateWorkspacePanel({ onClose }: { onClose: () => void }) {
  const { switchWorkspace } = useAuth();
  const createWorkspace = useCreateWorkspace();
  const form = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: "" },
  });

  async function onSubmit({ name }: z.infer<typeof createSchema>) {
    try {
      const created = await createWorkspace.mutateAsync(name);
      await switchWorkspace(created.id);
      toast.success(`${created.name} is ready. You're now working in it.`);
      onClose();
    } catch (err) {
      form.setError("name", { message: errorMessage(err) });
    }
  }

  return (
    <div
      role="dialog"
      aria-labelledby="create-workspace-title"
      className="glass-elevated absolute top-full left-0 z-50 mt-2 w-[min(20rem,calc(100vw-2rem))] rounded-card p-5 duration-150 animate-in fade-in-0"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <h2 id="create-workspace-title" className="mb-4 text-lg font-semibold">
        New workspace
      </h2>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Workspace name</FormLabel>
                <FormControl>
                  <Input autoFocus placeholder="Acme Support" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className="flex gap-3">
            <Button type="submit" size="sm" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? "Creating…" : "Create workspace"}
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
