import React from 'react';
type View = 'chat' | 'commands' | 'voice' | 'settings';
interface SidebarProps {
    activeView: View;
    onViewChange: (view: View) => void;
}
declare const Sidebar: React.FC<SidebarProps>;
export default Sidebar;
//# sourceMappingURL=Sidebar.d.ts.map