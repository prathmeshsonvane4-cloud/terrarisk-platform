import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LoginForm } from "@/features/auth/login-form";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-lg">TerraRisk</CardTitle>
          <CardDescription>Climate Intelligence for Agricultural Credit</CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm />
        </CardContent>
      </Card>
    </div>
  );
}
