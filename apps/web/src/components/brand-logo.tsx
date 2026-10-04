import Image from "next/image";

export function BrandLogo({ preload = false }: { preload?: boolean }) {
  return (
    <Image
      className="brand-logo"
      src="/brand/danaconnect-logo.jpg"
      alt="DanaConnect"
      width={640}
      height={640}
      unoptimized
      preload={preload}
    />
  );
}
