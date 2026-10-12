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
import { motion } from "motion/react";
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

interface SidebarNavProps {
  onNavigate?: () => void;
  collapsed?: boolean;
}

export function SidebarNav({ onNavigate, collapsed = false }: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="flex-1">
      <ul className="flex flex-col gap-1.5">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                title={collapsed ? label : undefined}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "pressable relative flex h-10 items-center gap-3 rounded-[6px] px-3 text-sm font-medium transition-colors",
                  active
                    ? "bg-white/[0.08] text-bone font-semibold"
                    : "text-ash hover:bg-white/[0.04] hover:text-bone",
                  collapsed && "justify-center px-0"
                )}
              >
                {active && (
                  <motion.span
                    layoutId="activeNavIndicator"
                    aria-hidden
                    className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-ion"
                    transition={{ type: "spring", stiffness: 400, damping: 35 }}
                  />
                )}
                <Icon className={cn("size-4 shrink-0 transition-colors", active ? "text-ion" : "text-ash")} aria-hidden />
                {!collapsed && <span className="truncate">{label}</span>}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
