import Image from "next/image";

const brandPath = `${process.env.NEXT_PUBLIC_ADMIN_BASE_PATH || ""}/brand`;

export function BrandLogo({ preload = false }: { preload?: boolean }) {
  return (
    <span className="brand-marks">
      <span className="brand-partner">
        <Image className="brand-logo" src={`${brandPath}/danaconnect-logo.jpg`} alt="DANA Connect" width={640} height={640} unoptimized preload={preload} />
      </span>
      <span className="brand-divider" aria-hidden="true" />
      <span className="brand-partner">
        <Image className="brand-logo wit-brand-logo" src={`${brandPath}/wit-kazakhstan.png`} alt="Women in Tech Kazakhstan" width={4500} height={4500} unoptimized preload={preload} />
      </span>
    </span>
  );
}
