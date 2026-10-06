import Image from "next/image";

export function BrandLogo({ preload = false, secondary = false }: { preload?: boolean; secondary?: boolean }) {
  return (
    <span className="brand-marks">
      <Image
        className="wit-brand-logo"
        src="/brand/wit-kazakhstan.png"
        alt="Women in Tech Kazakhstan"
        width={88}
        height={88}
        sizes="88px"
        preload={preload}
      />
      {secondary && <span className="brand-secondary">
        <Image className="brand-logo" src="/brand/danaconnect-logo.jpg" alt="DanaConnect" width={640} height={640} unoptimized />
      </span>}
    </span>
  );
}
