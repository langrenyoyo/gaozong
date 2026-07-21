import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

interface ChangePasswordDialogProps {
  open: boolean;
  submitting: boolean;
  errorMessage: string | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (oldPassword: string, newPassword: string) => void;
}

const MIN_PASSWORD_LENGTH = 8;

/**
 * 商户自助改密弹窗。
 *
 * 仅做前端可访问性与基本校验（空值、长度、新旧不同、两次一致）；不得在错误消息、日志或 URL 中
 * 回显密码内容。提交中禁用按钮并暴露 aria-live 状态。
 */
export default function ChangePasswordDialog({
  open,
  submitting,
  errorMessage,
  onOpenChange,
  onSubmit,
}: ChangePasswordDialogProps) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  // 密码只保留在组件内存，不持久化；关闭/卸载时清空。
  const oldPasswordRef = useRef<HTMLInputElement>(null);

  const resetFields = () => {
    setOldPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setValidationError(null);
  };

  // 打开时聚焦原密码输入（仅 DOM 副作用，不在此 setState）；字段重置由 handleOpenChange/handleSubmit 负责。
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => oldPasswordRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [open]);

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      resetFields();
    }
    onOpenChange(next);
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;

    if (!oldPassword.trim() || !newPassword.trim() || !confirmPassword.trim()) {
      setValidationError("请填写完整密码信息");
      return;
    }
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setValidationError(`新密码至少 ${MIN_PASSWORD_LENGTH} 位`);
      return;
    }
    if (newPassword === oldPassword) {
      setValidationError("新密码不能与原密码相同");
      return;
    }
    if (newPassword !== confirmPassword) {
      setValidationError("两次输入的新密码不一致");
      return;
    }
    setValidationError(null);
    onSubmit(oldPassword, newPassword);
    // 提交后立即清空本地密码副本，仅依赖后端结果与外部 submitting 状态。
    resetFields();
  };

  const shownError = validationError || errorMessage;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>修改密码</DialogTitle>
          <DialogDescription>修改成功后需重新登录，系统不会保存或回显你的密码。</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="change-password-old">原密码</Label>
            <Input
              id="change-password-old"
              ref={oldPasswordRef}
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(event) => setOldPassword(event.target.value)}
              disabled={submitting}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="change-password-new">新密码（至少 {MIN_PASSWORD_LENGTH} 位）</Label>
            <Input
              id="change-password-new"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              disabled={submitting}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="change-password-confirm">确认新密码</Label>
            <Input
              id="change-password-confirm"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              disabled={submitting}
            />
          </div>
          {shownError ? (
            <p role="alert" aria-live="assertive" className="text-sm font-medium text-rose-500">
              {shownError}
            </p>
          ) : null}
          {submitting ? (
            <p role="status" aria-live="polite" className="text-sm text-slate-500">
              正在提交...
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)} disabled={submitting}>
              取消
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "提交中..." : "确认修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
