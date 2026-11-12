import { IsOptional, IsString, IsUrl, Matches } from 'class-validator';

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
}
