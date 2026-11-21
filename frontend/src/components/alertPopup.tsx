import React from "react";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "./ui/alert";
import { LucideIcon } from "lucide-react";

type AlertType = "default" | "destructive" | "warning";

interface Props {
  title: string;
  description: string;
  icon: LucideIcon;
  children: React.ReactNode;
  variant?: AlertType;
}

export default function AlertPopup({
  title,
  description,
  icon: Icon,
  children: actionNode,
  variant = "default",
}: Props) {
  return (
    <Alert
      variant={
        variant === "default" || variant === "destructive" ? variant : undefined
      }
      className={
        variant == "warning"
          ? "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-50"
          : ""
      }
    >
      <Icon className="text-amber-900 dark:text-amber-50" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{description}</AlertDescription>
      <AlertAction>{actionNode}</AlertAction>
    </Alert>
  );
}
