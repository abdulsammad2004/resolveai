"use client";

import { LogOut, Settings } from "lucide-react";
import Link from "next/link";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth/auth-provider";
import { initials } from "@/lib/utils";

export function UserMenu() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="pressable rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ion"
        aria-label={`Account menu for ${user.full_name}`}
      >
        <Avatar className="size-8 border border-line bg-carbon-elevated text-xs font-semibold text-bone">
          <AvatarFallback>{initials(user.full_name)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="flex flex-col gap-0.5 pb-2">
          <span className="truncate text-sm font-semibold text-bone">{user.full_name}</span>
          <span className="truncate text-xs font-normal text-ash">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings" className="flex items-center">
            <Settings className="size-4 mr-2 text-ash" aria-hidden />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={() => void logout()} className="text-urgent">
          <LogOut className="size-4 mr-2" aria-hidden />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
