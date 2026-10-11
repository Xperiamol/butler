import Link from "next/link";
import Image from "next/image";

export default function Brand({ href = "/", inverse = false }: { href?: string; inverse?: boolean }) {
  return <Link href={href} className={`brand ${inverse ? "inverse" : ""}`} aria-label="Butler 首页">
    <Image className="brand-mark" src="/butler-avatar.png" width={64} height={64} alt="" />
    <span>butler<span className="brand-period">.</span></span>
  </Link>;
}
