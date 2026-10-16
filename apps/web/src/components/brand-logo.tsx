import Image from "next/image";

export function BrandLogo({ preload = false }: { preload?: boolean }) {
  return (
    <span className="brand-marks">
      <span className="brand-partner">
        <Image className="brand-logo" src="/brand/danaconnect-logo.jpg" alt="DANA Connect" width={640} height={640} preload={preload} unoptimized />
      </span>
      <span className="brand-divider" aria-hidden="true" />
      <span className="brand-partner">
        <Image
          className="brand-logo wit-brand-logo"
          src="/brand/wit-kazakhstan.png"
          alt="Women in Tech Kazakhstan"
          width={4500}
          height={4500}
          sizes="112px"
          preload={preload}
          unoptimized
        />
      </span>
    </span>
  );
}
