import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function HomeIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 10.5 10 4l7 6.5" />
      <path d="M5 9.5V16a1 1 0 0 0 1 1h3v-4h2v4h3a1 1 0 0 0 1-1V9.5" />
    </Icon>
  );
}

export function MailIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="5" width="14" height="10" rx="2" />
      <path d="M4 6.5 10 11l6-4.5" />
    </Icon>
  );
}

export function UsersIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="7.2" cy="7" r="2.6" />
      <path d="M2.3 16.2c.5-3.2 2.1-4.8 4.9-4.8s4.4 1.6 4.9 4.8" />
      <circle cx="14.5" cy="8" r="2" />
      <path d="M12.8 11.6c2.1.2 3.2 1.6 3.7 4" />
    </Icon>
  );
}

export function ShieldIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 3.2 15.5 5v4.4c0 4-2.4 6.2-5.5 6.8-3.1-.6-5.5-2.8-5.5-6.8V5l5.5-1.8z" />
    </Icon>
  );
}

export function GroupsIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="3" width="6" height="6" rx="1.3" />
      <rect x="11" y="3" width="6" height="6" rx="1.3" />
      <rect x="3" y="11" width="6" height="6" rx="1.3" />
      <rect x="11" y="11" width="6" height="6" rx="1.3" />
    </Icon>
  );
}

export function LockIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="4" y="9" width="12" height="8" rx="2.2" />
      <path d="M6.5 9V6.6a3.5 3.5 0 0 1 7 0V9" />
    </Icon>
  );
}

export function LayersIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 3 3 7l7 4 7-4-7-4z" />
      <path d="M3 11l7 4 7-4" />
    </Icon>
  );
}

export function BookIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 4.3h4.6c1 0 1.8.8 1.8 1.8v9.6c0-1-.8-1.8-1.8-1.8H4V4.3z" />
      <path d="M16 4.3h-4.6c-1 0-1.8.8-1.8 1.8v9.6c0-1 .8-1.8 1.8-1.8H16V4.3z" />
    </Icon>
  );
}

export function CompassIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="6.8" />
      <path d="M12.8 7.2 11 11l-3.8 1.8L9 9l3.8-1.8z" />
    </Icon>
  );
}

export function SunIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="3.4" />
      <path d="M10 2.6v1.8M10 15.6v1.8M17.4 10h-1.8M4.4 10H2.6M15.3 4.7l-1.3 1.3M6 14l-1.3 1.3M15.3 15.3 14 14M6 6 4.7 4.7" />
    </Icon>
  );
}

export function MoonIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M15.2 11.7A6 6 0 0 1 8.3 4.8a6 6 0 1 0 6.9 6.9z" />
    </Icon>
  );
}

export function ContrastIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="6.5" />
      <path d="M10 3.5a6.5 6.5 0 0 1 0 13z" fill="currentColor" stroke="none" />
    </Icon>
  );
}

export function SidebarLeftIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="3.5" width="14" height="13" rx="2" />
      <path d="M8.2 3.5v13" />
    </Icon>
  );
}

export function SidebarTopIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="3.5" width="14" height="13" rx="2" />
      <path d="M3 8h14" />
    </Icon>
  );
}

export function CameraIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3" y="6.6" width="14" height="9.8" rx="2" />
      <circle cx="10" cy="11.5" r="2.8" />
      <path d="M8 6.6l.9-1.8h2.2l.9 1.8" />
    </Icon>
  );
}
