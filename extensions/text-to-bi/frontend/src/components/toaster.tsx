import React from 'react';
import { Toast } from '@base-ui/react/toast';
import { CircleAlertIcon, CircleCheckIcon, InfoIcon, TriangleAlertIcon, XIcon } from 'lucide-react';
import { cn } from 'cn';

import { usePortalContainer } from '@/lib/portal-container';

// One manager for the whole page, so code outside React (a save handler, a stream) can raise a toast.
const toastManager = Toast.createToastManager();

type ToastOptions = { description?: string; action?: { label: string; onClick: () => void } };

// The options follow sonner's: a second line, which the standalone app uses for the name of what changed, and an action
// button (such as "Hoàn tác") that closes the toast once clicked.
const show = (type: string) => (title: string, options?: ToastOptions) => {
  const action = options?.action;
  const id: string = toastManager.add({
    title,
    description: options?.description,
    type,
    timeout: 5000,
    actionProps: action && {
      children: action.label,
      onClick: () => {
        action.onClick();
        toastManager.close(id);
      },
    },
  });
  return id;
};

export const toast = {
  success: show('success'),
  error: show('error'),
  warning: show('warning'),
  info: show('info'),
};

const icons: Record<string, React.ReactNode> = {
  success: <CircleCheckIcon className="text-emerald-600 dark:text-emerald-400" />,
  error: <CircleAlertIcon className="text-destructive" />,
  warning: <TriangleAlertIcon className="text-amber-600 dark:text-amber-400" />,
  info: <InfoIcon className="text-muted-foreground" />,
};

function ToastList() {
  const { toasts } = Toast.useToastManager();
  return (
    <>
      {toasts.map(item => (
        <Toast.Root
          key={item.id}
          toast={item}
          className={cn(
            'flex w-80 items-start gap-2.5 rounded-lg border bg-popover px-3.5 py-3 text-sm text-popover-foreground ' +
              'shadow-lg transition-all duration-200 data-ending-style:opacity-0 data-starting-style:opacity-0 ' +
              '[&_svg]:size-4 [&_svg]:shrink-0'
          )}
        >
          <span className="mt-0.5">{icons[item.type ?? 'info']}</span>
          <Toast.Content className="min-w-0 flex-1">
            <Toast.Title className="leading-snug" />
            <Toast.Description className="text-muted-foreground" />
          </Toast.Content>
          <Toast.Action className="shrink-0 rounded-md border px-2 py-0.5 text-xs font-medium hover:bg-muted" />
          <Toast.Close aria-label="Đóng thông báo" className="text-muted-foreground hover:text-foreground">
            <XIcon />
          </Toast.Close>
        </Toast.Root>
      ))}
    </>
  );
}

// Render once per page; toasts open inside the extension root so they keep its theme tokens.
export function Toaster() {
  return (
    <Toast.Provider toastManager={toastManager}>
      <Toast.Portal container={usePortalContainer()}>
        <Toast.Viewport className="fixed right-4 bottom-4 z-[100] flex flex-col-reverse gap-2 outline-none">
          <ToastList />
        </Toast.Viewport>
      </Toast.Portal>
    </Toast.Provider>
  );
}
