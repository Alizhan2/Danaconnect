"use client";
import { AdminShell } from "@/components/shell";
import { AIReviewPanel } from "@/components/ai-review";

export default function Page() {
  return <AdminShell title="aiReview"><AIReviewPanel /></AdminShell>;
}
