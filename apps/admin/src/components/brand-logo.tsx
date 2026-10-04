import Image from "next/image";

const logoPath = `${process.env.NEXT_PUBLIC_ADMIN_BASE_PATH || ""}/brand/danaconnect-logo.jpg`;

export function BrandLogo({ preload = false }: { preload?: boolean }) {
  return (
    <Image
      className="brand-logo"
      src={logoPath}
      alt="DanaConnect"
      width={640}
      height={640}
      unoptimized
      preload={preload}
    />
  );
}
