"use client";

import { PriorityQueueView } from "@/features/water-intelligence/priority-queue/priority-queue-view";

export default function PriorityQueuePage() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 p-4 md:p-6">
      <PriorityQueueView />
    </div>
  );
}
