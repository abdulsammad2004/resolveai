"use client";

import {
  BookOpen,
  Inbox,
  LayoutDashboard,
  MessagesSquare,
  Settings,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

type NavItem = { href: string; label: string; icon: LucideIcon };

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/tickets", label: "Inbox", icon: Inbox },
  { href: "/approvals", label: "Approvals", icon: ShieldCheck },
  { href: "/conversations", label: "Conversations", icon: MessagesSquare },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main">
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "pressable relative flex h-11 items-center gap-3 rounded-card px-3.5 text-base font-medium transition-colors",
                  active
                    ? "bg-white/[0.12] text-mist shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.14)]"
                    : "text-mist-dim hover:bg-white/[0.07] hover:text-mist",
                )}
              >
                {active && (
                  <span
                    aria-hidden
                    className="absolute top-2.5 bottom-2.5 left-0 w-[3px] rounded-full bg-seafoam"
                  />
                )}
                <Icon className={cn("size-[18px]", active && "text-seafoam")} aria-hidden />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
