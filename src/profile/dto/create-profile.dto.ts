import { Type } from 'class-transformer';
import {
  IsArray,
  IsBoolean,
  IsIn,
  IsOptional,
  IsString,
  IsUrl,
  Matches,
  ValidateNested,
} from 'class-validator';

export const PROFILE_THEMES = [
  'amber',
  'violet',
  'emerald',
  'crimson',
  'azure',
  'rose',
  'slate',
  'ocean',
] as const;
export type ProfileTheme = (typeof PROFILE_THEMES)[number];

export const PROFILE_ANIMATIONS = ['none', 'fade', 'particles', 'matrix', 'tilt'] as const;
export type ProfileAnimation = (typeof PROFILE_ANIMATIONS)[number];

export const SIZES = ['small', 'medium', 'large'] as const;
export type Size = (typeof SIZES)[number];

export const SECTION_KEYS = [
  'skills',
  'internships',
  'projects',
  'education',
  'certifications',
] as const;
export type SectionKey = (typeof SECTION_KEYS)[number];

export class SectionConfigItemDto {
  @IsIn(SECTION_KEYS)
  key!: SectionKey;

  @IsBoolean()
  visible!: boolean;
}

export class CreateProfileDto {
  @Matches(/^[a-z0-9-]{3,30}$/, {
    message: 'username must be 3-30 lowercase letters, numbers or hyphens',
  })
  username!: string;

  @IsString()
  name!: string;

  @IsString()
  title!: string;

  @IsOptional()
  @IsString()
  tagline?: string;

  @IsOptional()
  @IsString()
  bio?: string;

  @IsOptional()
  @IsString()
  phone?: string;

  @IsOptional()
  @IsUrl()
  avatar_url?: string;

  @IsOptional()
  @IsUrl()
  resume_url?: string;

  @IsOptional()
  @IsIn(PROFILE_THEMES)
  theme?: ProfileTheme;

  @IsOptional()
  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => SectionConfigItemDto)
  section_config?: SectionConfigItemDto[];

  @IsOptional()
  @IsIn(PROFILE_ANIMATIONS)
  animation?: ProfileAnimation;

  @IsOptional()
  @IsIn(SIZES)
  avatar_size?: Size;

  @IsOptional()
  @IsIn(SIZES)
  text_size?: Size;
}
