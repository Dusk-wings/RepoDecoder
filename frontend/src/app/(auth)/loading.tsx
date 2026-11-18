import { Card } from "@/components/ui/card";

export default function AuthLoading() {
  return (
    <Card>
      <div className="flex gap-2 flex-col p-2">
        <div className="h-11 w-1/2 animate-pulse bg-muted rounded-xl"></div>
        <div className="animate-pulse h-52 w-full bg-muted rounded-xl"></div>
        <div className="h-16 w-1/2 animate-pulse bg-muted rounded-xl"></div>
      </div>
    </Card>
  );
}
