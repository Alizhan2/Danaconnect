"use client";

import { use } from "react";
import { DemoMentorProfile } from "@/components/demo-mentors";

export default function DemoMentorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <DemoMentorProfile key={id} id={id} />;
}
