import { AppHeader, type AppHeaderProps } from '@wsl/ui';

export type HeaderProps = AppHeaderProps;

export default function Header(props: HeaderProps) {
  return <AppHeader {...props} />;
}
