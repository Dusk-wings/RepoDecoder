import { verificationFor } from "@/lib/verifyTurnstile";
import TurnstileWidget from "./turnstileWidget";
import { Button } from "./ui/button";
import {
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "./ui/dialog";
import { Spinner } from "./ui/spinner";

interface Props {
  title: string;
  description: string;
  button_text: string;
  token: string | null;
  action: verificationFor;
  isProcessing: boolean;

  setToken: (token: string | null) => void;
  activationFunction: () => void;
  setOpen: (value: boolean) => void;
}

export default function TurnstilePopUp({
  title,
  description,
  button_text,
  token,
  action,
  isProcessing,
  setToken,
  activationFunction,
  setOpen,
}: Props) {
  return (
    <DialogContent
      className="sm:max-w-sm"
      onEscapeKeyDown={(e) => {
        if (isProcessing) e.preventDefault();
      }}
      onInteractOutside={(e) => {
        if (isProcessing) e.preventDefault();
      }}
    >
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      <div>
        <TurnstileWidget onVerify={setToken} action={action} />
      </div>
      <DialogFooter>
        <DialogClose asChild>
          <Button
            variant="outline"
            disabled={isProcessing}
            onClick={() => {
              setToken(null);
              setOpen(false);
            }}
          >
            Cancel
          </Button>
        </DialogClose>
        <Button onClick={activationFunction} disabled={!token || isProcessing}>
          {isProcessing ? (
            <span className="flex flex-row gap-2 justify-center items-center">
              <Spinner /> <span>Processing .. </span>
            </span>
          ) : (
            button_text
          )}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
