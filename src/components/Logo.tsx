import Image from "next/image";

const SIZE_CLASSES = {
  sm: "h-8 w-8",
  md: "h-9 w-9",
};

const SIZE_PX = {
  sm: 32,
  md: 36,
};

export function LogoMark({ size = "md" }: { size?: keyof typeof SIZE_CLASSES }) {
  return (
    <div
      className={`relative ${SIZE_CLASSES[size]} flex-none overflow-hidden rounded-[9px]`}
    >
      <Image
        src="/logo.jpg"
        alt="SmartAcademy"
        width={SIZE_PX[size]}
        height={SIZE_PX[size]}
        className="h-full w-full object-cover"
        priority
      />
    </div>
  );
}

export default function Logo({ subtitle }: { subtitle?: string }) {
  return (
    <div className="flex items-center gap-3">
      <LogoMark />
      <div className="font-display font-bold leading-none">
        SmartAcademy
        {subtitle && (
          <small className="mt-0.5 block text-[11px] font-medium leading-none text-muted">
            {subtitle}
          </small>
        )}
      </div>
    </div>
  );
}
