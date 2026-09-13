import React from 'react';
type View = 'chat' | 'commands' | 'monitor' | 'voice';
interface SidebarProps {
    activeView: View;
    onViewChange: (view: View) => void;
    onSettingsClick: () => void;
}
declare const Sidebar: React.FC<SidebarProps>;
export default Sidebar;
//# sourceMappingURL=Sidebar.d.ts.map