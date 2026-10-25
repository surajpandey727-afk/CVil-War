import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import RichText from '@/components/assistant/RichText';

describe('RichText (assistant replies)', () => {
  it('renders bold, bullets and paragraphs instead of raw markdown', () => {
    const { container } = render(
      <RichText text={'**Best matches**\n\n- **Senior PM at Monzo** — 37%\n- 3 others unscored\n\nNothing waiting.'} />,
    );
    expect(screen.getByText('Best matches').tagName).toBe('STRONG');
    expect(container.querySelectorAll('ul li')).toHaveLength(2);
    expect(container.textContent).not.toContain('**');
    expect(screen.getByText('Nothing waiting.')).toBeInTheDocument();
  });

  it('numbered lists stay numbered', () => {
    const { container } = render(<RichText text={'1. Upload a CV\n2. Run the check'} />);
    expect(container.querySelectorAll('ol li')).toHaveLength(2);
  });

  it('never turns text into HTML — markup in a reply stays inert text', () => {
    const { container } = render(<RichText text={'<img src=x onerror="alert(1)"> **ok**'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });
});
